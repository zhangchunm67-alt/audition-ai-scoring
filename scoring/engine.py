"""计分引擎：证据 + 配置 + 上下文 → 一轮的分数。纯函数，不读写任何外部状态。

计算全程用 Fraction，只在维度分取整时四舍五入（half-up），避免浮点和银行家舍入的误差。
"""
from __future__ import annotations

import math
from collections import defaultdict
from fractions import Fraction
from typing import Iterable

from .config import (
    LevelPart,
    RubricConfig,
    T1Item,
    T2Item,
    T3T4Item,
    T4Item,
    T5Item,
    T6Item,
    config_hash,
)
from .types import (
    COUNT,
    NOT_COUNT,
    Contribution,
    DimensionResult,
    Evidence,
    ItemResult,
    RedlineHit,
    RoundResult,
    ScoringContext,
)


class EvidenceError(ValueError):
    """证据与配置不符（检测器的 bug），不能静默忽略。"""


class ScoringInputError(ValueError):
    """上下文不完整或与配置不符。"""


class _Missing(Exception):
    """某条目缺少必需证据：不出分，也不当作“没有扣分事件”。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def round_half_up(x: Fraction) -> int:
    if x < 0:
        raise ValueError("维度分不应为负")
    return math.floor(x + Fraction(1, 2))


def _order(evs: Iterable[Evidence]) -> list[Evidence]:
    return sorted(evs, key=lambda e: (e.start_ms is None, e.start_ms or 0, e.evidence_id))


def _binary(e: Evidence) -> bool:
    j = e.effective_judgment()
    if j not in (COUNT, NOT_COUNT):
        raise EvidenceError(f"{e.evidence_id}: {e.kind} 证据的 judgment 应为 count / not_count，实际为 {j!r}")
    return j == COUNT


def _only_kinds(item_id: str, evs: list[Evidence], kinds: set[str]) -> None:
    for e in evs:
        if e.kind not in kinds:
            raise EvidenceError(f"{e.evidence_id}: 条目 {item_id} 不接受 {e.kind} 类证据")


def _f(x: Fraction | int) -> float:
    return float(x)


# ───────────────────────── 各计分类型 ─────────────────────────


def _time_factor(norm, ctx: ScoringContext, res: ItemResult, what: str) -> Fraction:
    """按时长换算的系数：每 per_minutes 分钟的次数 = 次数 × per_minutes ÷ 实际分钟数。不换算时为 1。"""
    if not (norm and norm.enabled):
        return Fraction(1)
    if ctx.main_duration_ms is None or ctx.main_duration_ms <= 0:
        raise _Missing("缺少主体段时长，无法按时长换算次数")
    full_ms = norm.per_minutes * 60_000
    if ctx.main_duration_ms == full_ms or (ctx.main_duration_ms > full_ms and not norm.both_ways):
        return Fraction(1)
    factor = Fraction(full_ms, ctx.main_duration_ms)
    why = "不足" if ctx.main_duration_ms < full_ms else "超过"
    res.notes.append(f"主体段{why} {norm.per_minutes} 分钟，按 {what} × {norm.per_minutes} ÷ {ctx.main_duration_ms / 60000:.2f} 分钟换算")
    return factor


def _score_t1(item: T1Item, evs: list[Evidence], ctx: ScoringContext, res: ItemResult) -> Fraction:
    _only_kinds(item.id, evs, {"occurrence"})
    occ = [e for e in _order(evs) if _binary(e)]
    n: Fraction = Fraction(len(occ))
    factor = _time_factor(item.normalize, ctx, res, f"{len(occ)} 次")
    n = n * factor
    over = max(Fraction(0), n - item.free)
    score = max(Fraction(0), item.max - item.per * over)
    # 逐句贡献：按时间顺序，前 free 处不扣（换算时按比例分摊，仅供展示）
    remaining = Fraction(item.max)
    for i, e in enumerate(occ):
        if factor != 1:
            d, note = Fraction(0), "按时长换算后统一扣分"
        elif i < item.free:
            d, note = Fraction(0), "免扣次数内"
        else:
            d = min(Fraction(item.per), remaining)
            remaining -= d
            note = f"扣 {item.per} 分" if d == item.per else "已扣到 0"
        res.contributions.append(Contribution(evidence_id=e.evidence_id, delta=-_f(d), note=note))
    res.notes.append(f"计 {len(occ)} 次，免扣 {item.free} 次")
    return score


def _score_t2(item: T2Item, evs: list[Evidence], ctx: ScoringContext, res: ItemResult) -> Fraction:
    _only_kinds(item.id, evs, {"instance"})
    total = 0
    raw = 0  # 不封顶的合计，按时长换算时用
    seen: set[str] = set()
    for e in _order(evs):
        if not _binary(e):
            continue
        label = e.label
        if item.awards is not None:
            pts = item.awards.get(label or "")
        else:
            pts = item.award if (item.labels is None or label in item.labels) else None
        if pts is None:
            res.contributions.append(Contribution(evidence_id=e.evidence_id, delta=0, note=f"类别 {label!r} 不计分"))
            continue
        if item.distinct_by_label:
            if not label:
                raise EvidenceError(f"{e.evidence_id}: {item.id} 按类别去重，证据须有 label")
            if label in seen:
                res.contributions.append(Contribution(evidence_id=e.evidence_id, delta=0, note="同一类别已计分"))
                continue
            seen.add(label)
        raw += pts
        add = min(pts, item.max - total)
        total += add
        res.contributions.append(
            Contribution(evidence_id=e.evidence_id, delta=add, note="已封顶" if add < pts else f"加 {pts} 分")
        )
    factor = _time_factor(item.normalize, ctx, res, f"{raw} 分")
    if factor != 1:  # 先按时长换算再封顶；逐条贡献改为统一说明
        for c in res.contributions:
            if c.delta:
                c.delta, c.note = 0, "按时长换算后统一计分"
        return min(Fraction(item.max), raw * factor)
    return Fraction(total)


def _score_t3t4(item: T3T4Item, evs: list[Evidence], ctx: ScoringContext, res: ItemResult) -> Fraction:
    _only_kinds(item.id, evs, {"checklist_hit", "level", "occurrence"})
    if not ctx.checklist:
        raise _Missing("缺少卖点卡必讲要点")
    card_total = sum(p.points for p in ctx.checklist)
    if card_total != item.checklist_max:
        raise ScoringInputError(
            f"{item.id}: 卖点卡要点分值合计 {card_total}，与配置的要点满分 {item.checklist_max} 不一致"
            "（处理方式待确认，见 decisions.md P-S2-CARD）"
        )
    points = {p.id: p for p in ctx.checklist}
    by_point: dict[str, list[Evidence]] = defaultdict(list)
    structure: list[Evidence] = []
    errors: list[Evidence] = []
    for e in _order(evs):
        if e.kind == "checklist_hit":
            if e.ref not in points:
                raise EvidenceError(f"{e.evidence_id}: 要点 {e.ref!r} 不在卖点卡中")
            by_point[e.ref].append(e)
        elif e.kind == "level":
            if e.ref not in (None, "structure"):
                raise EvidenceError(f"{e.evidence_id}: {item.id} 的等级证据 ref 应为 structure")
            structure.append(e)
        else:
            if e.label != item.error_label:
                raise EvidenceError(f"{e.evidence_id}: {item.id} 的逐次证据只用于讲错（label={item.error_label}）")
            if _binary(e):
                errors.append(e)
    unchecked = [p.name for pid, p in points.items() if pid not in by_point]
    if unchecked:
        raise _Missing("要点未核对：" + "、".join(unchecked))
    if len(structure) != 1:
        if not structure:
            raise _Missing("缺少结构等级")
        raise EvidenceError(f"{item.id}: 结构等级证据应只有 1 条，实际 {len(structure)} 条")
    s_level = structure[0].effective_judgment()
    if s_level not in item.structure_levels:
        raise EvidenceError(f"{structure[0].evidence_id}: 结构等级 {s_level!r} 不在 {item.structure_levels}")

    total = Fraction(0)
    for pid, p in points.items():
        hit_ev = next((e for e in by_point[pid] if _binary(e)), None)
        if hit_ev is not None:
            total += p.points
            res.contributions.append(Contribution(evidence_id=hit_ev.evidence_id, delta=p.points, note=f"要点：{p.name}"))
        elif p.compliance_required:
            res.notes.append(f"合规必讲要点未讲：{p.name}")
    total += s_level
    res.contributions.append(Contribution(evidence_id=structure[0].evidence_id, delta=s_level, note="结构等级"))
    remaining = total
    for e in errors:
        d = min(Fraction(item.error_penalty), remaining)
        remaining -= d
        res.contributions.append(Contribution(evidence_id=e.evidence_id, delta=-_f(d), note=f"讲错扣 {item.error_penalty} 分"))
    return max(Fraction(0), total - item.error_penalty * len(errors))


def _metric_values(evs: list[Evidence]) -> dict[str, Evidence]:
    out: dict[str, Evidence] = {}
    for e in evs:
        if e.kind != "metric":
            continue
        if not e.label or e.value is None:
            raise EvidenceError(f"{e.evidence_id}: 指标证据须有 label 和 value")
        if e.label in out:
            raise EvidenceError(f"{e.evidence_id}: 指标 {e.label} 重复")
        out[e.label] = e
    return out


_OPS = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
}


def _part_level(item: T4Item, part: LevelPart, evs: list[Evidence], res: ItemResult) -> int:
    single = len(item.parts) == 1
    if part.source == "evidence":
        mine = [e for e in evs if e.kind == "level" and (e.ref == part.id or (single and e.ref is None))]
        if not mine:
            raise _Missing(f"缺少等级证据（{part.id}）")
        if len(mine) > 1:
            raise EvidenceError(f"{item.id}.{part.id}: 等级证据应只有 1 条，实际 {len(mine)} 条")
        level = mine[0].effective_judgment()
        if level not in part.levels:
            raise EvidenceError(f"{mine[0].evidence_id}: 等级 {level!r} 不在 {part.levels}")
        src = mine[0].evidence_id
    elif part.source == "metric":
        metrics = _metric_values(evs)
        if part.metric not in metrics:
            raise _Missing(f"缺少指标 {part.metric}")
        ev = metrics[part.metric]
        v = ev.value
        level = next(b.level for b in part.metric_bands if b.min is None or v >= b.min)  # type: ignore[operator]
        src = ev.evidence_id
        bf = part.boundary_flag
        if bf and bf.enabled and bf.margin is not None:
            for b in part.metric_bands:
                if b.min is not None and abs(v - b.min) <= bf.margin:  # type: ignore[operator]
                    res.low_confidence_reasons.append(f"{part.metric}={v:g} 距分段边界 {b.min:g} 在 ±{bf.margin:g} 内")
                    break
    elif part.source == "count":
        occ = [e for e in evs if e.kind == "occurrence" and e.label in part.count_labels and _binary(e)]
        n = len(occ)
        level = next(b.level for b in part.count_bands if n >= b.min and (b.max is None or n <= b.max))
        src = None
        for e in _order(occ):
            res.contributions.append(Contribution(evidence_id=e.evidence_id, delta=0, note=f"计入{part.id}次数"))
        res.notes.append(f"{'、'.join(part.count_labels)} 合计 {n} 次")
        bf = part.boundary_flag
        if bf and bf.enabled and n in bf.counts:
            res.low_confidence_reasons.append(f"次数 {n} 落在分级交界")
    else:  # rules
        metrics = _metric_values(evs)
        needed = {c.metric for r in part.rules for c in r.all}
        absent = sorted(needed - set(metrics))
        if absent:
            raise _Missing("缺少指标 " + "、".join(absent))
        level = None
        for r in part.rules:
            if r.default or all(_OPS[c.op](metrics[c.metric].value, c.value) for c in r.all):
                level = r.level
                break
        assert level is not None
        src = None
    for m in part.modifiers:
        if not m.enabled:
            continue
        trig = [e for e in evs if e.label == m.label and e.kind != "metric" and _binary(e)]
        if not trig:
            continue
        before = level
        if m.cap is not None:
            level = min(level, m.cap)
        else:
            idx = min(part.levels.index(level) + (m.downgrade or 0), len(part.levels) - 1)
            level = part.levels[idx]
        res.notes.append(f"{m.label}：等级 {before} → {level}")
        res.contributions.append(Contribution(evidence_id=trig[0].evidence_id, delta=level - before, note=f"{m.label} 修正"))
    if src:
        res.contributions.append(Contribution(evidence_id=src, delta=level, note=f"等级（{part.id}）"))
    return level


def _score_t4(item: T4Item, evs: list[Evidence], res: ItemResult) -> Fraction:
    _only_kinds(item.id, evs, {"level", "metric", "occurrence"})
    level_parts = {p.id for p in item.parts if p.source == "evidence"}
    single = len(item.parts) == 1
    occ_labels = {lab for p in item.parts for lab in p.count_labels} | {m.label for p in item.parts for m in p.modifiers}
    metric_labels = {p.metric for p in item.parts if p.metric} | {c.metric for p in item.parts for r in p.rules for c in r.all}
    for e in evs:  # 不让任何证据被静默忽略
        if e.kind == "level":
            ref = e.ref if e.ref is not None else (item.parts[0].id if single else None)  # 单部分条目可省略 ref
            if ref not in level_parts:
                raise EvidenceError(f"{e.evidence_id}: {item.id} 的子项 {e.ref!r} 不接受检测器直接给等级")
        elif e.kind == "occurrence" and e.label not in occ_labels:
            raise EvidenceError(f"{e.evidence_id}: {item.id} 不使用标签为 {e.label!r} 的逐次证据")
        elif e.kind == "metric" and e.label not in metric_labels:
            raise EvidenceError(f"{e.evidence_id}: {item.id} 不使用指标 {e.label!r}")
    return Fraction(sum(_part_level(item, p, evs, res) for p in item.parts))


def _score_t5(item: T5Item, evs: list[Evidence], ctx: ScoringContext, res: ItemResult) -> Fraction:
    _only_kinds(item.id, evs, {"metric"})
    mine = [e for e in _order(evs) if e.label == item.metric]
    if len(mine) != len(evs):
        raise EvidenceError(f"{item.id}: 只接受指标 {item.metric}")
    if not mine:
        raise _Missing(f"缺少指标 {item.metric}")
    over = 0
    for e in mine:
        if e.value is None:
            raise EvidenceError(f"{e.evidence_id}: 指标缺少 value")
        if e.value > item.limit:
            over += 1
            res.contributions.append(Contribution(evidence_id=e.evidence_id, delta=0, note=f"{e.value:g} 超过上限 {item.limit:g}"))
    res.notes.append(f"{len(mine)} 段中 {over} 段超过上限 {item.limit:g}")
    factor = _time_factor(item.normalize, ctx, res, f"{over} 段")
    if factor != 1:
        over = int(over * factor + Fraction(1, 2))  # 换算后四舍五入到整段
        res.notes.append(f"换算后按 {over} 段超限计")
    return Fraction(item.score_for(over))


def _score_t6(item: T6Item, evs: list[Evidence], ctx: ScoringContext, res: ItemResult) -> Fraction:
    _only_kinds(item.id, evs, {"question"})
    expected = ctx.expected_questions.get(item.id)
    if expected is None:
        raise _Missing("缺少本场的题目或异议列表")
    flexible = item.id in ctx.flexible_questions  # 录播：按实际标出的条数折算（decisions.md C37）
    if len(set(expected)) != len(expected) or (len(expected) != item.count and not flexible) or not expected:
        raise ScoringInputError(f"{item.id}: 本场应有 {item.count} 道不重复的题目，实际 {len(expected)}")
    by_q: dict[str, list[Evidence]] = defaultdict(list)
    for e in _order(evs):
        if e.ref not in expected:
            raise EvidenceError(f"{e.evidence_id}: {e.ref!r} 不是本场的题目或异议")
        by_q[e.ref].append(e)
    absent = [q for q in expected if q not in by_q]
    if absent:
        raise _Missing("以下题目没有判定证据：" + "、".join(absent))
    total = Fraction(0)
    for q in expected:
        qevs = by_q[q]
        if item.levels is not None:
            if len(qevs) != 1:
                raise EvidenceError(f"{item.id}/{q}: 应只有 1 条逐题证据，实际 {len(qevs)} 条")
            j = qevs[0].effective_judgment()
            if j not in item.levels:
                raise EvidenceError(f"{qevs[0].evidence_id}: 等级 {j!r} 不在 {list(item.levels)}")
            pts = item.levels[j]
            total += pts
            res.contributions.append(Contribution(evidence_id=qevs[0].evidence_id, delta=pts, note=f"{q}：{j}"))
        else:
            assert item.elements is not None
            zero = [e for e in qevs if e.label in item.zero_labels and _binary(e)]
            got: dict[str, Evidence] = {}
            for e in qevs:
                if e.label in item.zero_labels:
                    continue
                if e.label not in item.elements:
                    raise EvidenceError(f"{e.evidence_id}: 要素 {e.label!r} 不在 {list(item.elements)}")
                if _binary(e) and e.label not in got:
                    got[e.label] = e
            if zero:
                res.contributions.append(Contribution(evidence_id=zero[0].evidence_id, delta=0, note=f"{q}：{zero[0].label}，本题 0 分"))
                continue
            for lab, e in got.items():
                total += item.elements[lab]
                res.contributions.append(Contribution(evidence_id=e.evidence_id, delta=item.elements[lab], note=f"{q}：{lab}"))
    if len(expected) != item.count:
        scaled = total * item.count / len(expected)
        res.notes.append(f"实际 {len(expected)} 条（评分表按 {item.count} 条计），得分按 {_f(total):g} × {item.count} ÷ {len(expected)} = {_f(scaled):.2f} 折算")
        return scaled
    return total


def _score_item(it, evs: list[Evidence], ctx: ScoringContext, res: ItemResult) -> Fraction:
    if isinstance(it, T1Item):
        return _score_t1(it, evs, ctx, res)
    if isinstance(it, T2Item):
        return _score_t2(it, evs, ctx, res)
    if isinstance(it, T3T4Item):
        return _score_t3t4(it, evs, ctx, res)
    if isinstance(it, T4Item):
        return _score_t4(it, evs, res)
    if isinstance(it, T5Item):
        return _score_t5(it, evs, ctx, res)
    return _score_t6(it, evs, ctx, res)


# ───────────────────────── 维度汇总（流水线计分与金标准共用） ─────────────────────────


def dimension_result(cfg: RubricConfig, dim_id: str, name: str, raw: Fraction, app_max: int, complete: bool) -> DimensionResult:
    """按适用满分折算到 100 → 四舍五入 → 查档位。"""
    if complete and app_max:
        scaled = raw * 100 / app_max
        score_int = round_half_up(scaled)
        return DimensionResult(id=dim_id, name=name, status="scored", raw=_f(raw), applicable_max=app_max,
                               scaled=_f(scaled), score=score_int, grade=cfg.grade_for(score_int))
    return DimensionResult(id=dim_id, name=name, status="incomplete", raw=None, applicable_max=app_max, scaled=None, score=None, grade=None)


def total_verdict(cfg: RubricConfig, dims: list[DimensionResult], threshold: int) -> tuple[int | None, bool | None, bool | None]:
    """总档位、是否达标、是否临界。任一维度不完整则都为 None。"""
    if not all(d.status == "scored" for d in dims):
        return None, None, None
    total = sum(d.grade for d in dims)  # type: ignore[misc]
    band = cfg.critical.review_band
    return total, total < threshold, threshold - band <= total <= threshold + band - 1


# ───────────────────────── 一轮计分 ─────────────────────────


def score_round(evidence: list[Evidence], cfg: RubricConfig, ctx: ScoringContext) -> RoundResult:
    item_ids = {it.id for _, it in cfg.items()}
    redline_ids = set(cfg.redlines.ids)
    ids = [e.evidence_id for e in evidence]
    if len(set(ids)) != len(ids):
        raise EvidenceError("evidence_id 重复")
    by_item: dict[str, list[Evidence]] = defaultdict(list)
    redline_evs: list[Evidence] = []
    for e in evidence:
        if e.kind == "redline":
            if e.item_id not in redline_ids:
                raise EvidenceError(f"{e.evidence_id}: 红线编号 {e.item_id!r} 不在配置中")
            redline_evs.append(e)
        elif e.item_id in item_ids:
            by_item[e.item_id].append(e)
        else:
            raise EvidenceError(f"{e.evidence_id}: 条目 {e.item_id!r} 不在评分配置中（已删除的条目也不接受证据）")
    if ctx.audience not in cfg.thresholds:
        raise ScoringInputError(f"未知的达标线 {ctx.audience!r}")

    items: list[ItemResult] = []
    dims: list[DimensionResult] = []
    for dim in cfg.dimensions:
        raw = Fraction(0)
        app_max = 0
        complete = True
        for it in dim.items:
            res = ItemResult(item_id=it.id, name=it.name, dimension=dim.id, type=it.type, status="scored", score=None, max=it.max)
            evs = [e for e in by_item.get(it.id, []) if not e.excluded]
            dropped = [e for e in by_item.get(it.id, []) if e.excluded and e.review.reviewer == "system"]
            res.evidence_ids = [e.evidence_id for e in _order(evs)]
            items.append(res)
            if it.applicable_if == "props_available" and not ctx.props_available:
                res.status = "not_applicable"
                res.notes.append("画面里没有贴片或 KT 板，本条不适用")
                continue
            if it.id in ctx.flexible_questions and not ctx.expected_questions.get(it.id):
                res.status = "not_applicable"
                res.notes.append("整段视频里没有观众异议（没有人工标注，逐字稿里也没有识别到主播回应观众提问），本条不适用，维度按其余条目折算")
                continue
            app_max += it.max
            machine: Fraction | None = None
            why: str | None = None
            if it.id in ctx.human_only and it.id not in ctx.completed_detectors:
                why = "本条由评委人工打分"
            elif it.id not in ctx.completed_detectors:
                why = "检测器未成功完成"
            else:
                try:
                    machine = _score_item(it, evs, ctx, res)
                except _Missing as m:
                    why = m.reason
                    res.contributions.clear()
            if machine is not None and not 0 <= machine <= it.max:
                raise AssertionError(f"{it.id} 分数 {machine} 超出 0–{it.max}")
            hs = ctx.human_scores.get(it.id)
            if hs is not None:
                if hs.score > it.max or Fraction(str(hs.score)) * 2 != int(Fraction(str(hs.score)) * 2):
                    raise ScoringInputError(f"{it.id}: 人工分 {hs.score:g} 应为 0–{it.max} 之间的整数或半分")
                score = Fraction(str(hs.score))
                res.source, res.human = "human", hs
                res.suggested_score = None if machine is None else _f(machine)
                res.notes.append(f"人工打分 {hs.score:g}" + (f"（机器建议 {_f(machine):g}）" if machine is not None else ""))
            else:
                need = (it.id in ctx.human_only or it.id in ctx.human_confirm
                        or (it.id in ctx.human_on_deduction and machine is not None and machine < it.max)
                        or (machine is None and ctx.human_fallback))
                if need:
                    res.status, res.score = "awaiting_human", None
                    res.suggested_score = None if machine is None else _f(machine)
                    if it.id in ctx.human_only or it.id in ctx.human_confirm:
                        res.missing_reasons.append("本条须评委人工打分" if machine is None else "机器建议分须评委确认")
                    elif machine is not None:
                        res.missing_reasons.append("机器判为扣分，须评委确认")
                    if why and machine is None:
                        res.missing_reasons.append(f"机器未评出：{why}")
                    complete = False
                    continue
                if machine is None:
                    res.status = "missing_evidence"
                    res.missing_reasons.append(why or "缺少证据")
                    complete = False
                    continue
                score = machine
            res.score = _f(score)
            raw += score
            thr = cfg.low_conf_threshold(it)
            for e in _order(evs):
                if e.confidence < thr:
                    res.low_confidence_reasons.append(f"证据 {e.evidence_id} 置信度 {e.confidence:.2f} 低于 {thr:.2f}")
            if dropped:  # 机器自己排除的证据（如引用对不上原文）：不计分，但提醒复核
                res.low_confidence_reasons.append(f"有 {len(dropped)} 条机器证据因{dropped[0].review.note or '无法核对'}")
            res.low_confidence = bool(res.low_confidence_reasons) and res.source == "machine"
        dims.append(dimension_result(cfg, dim.id, dim.name, raw, app_max, complete))

    # 红线
    hits: list[RedlineHit] = []
    below: list[RedlineHit] = []
    for e in _order(redline_evs) if cfg.redlines.enabled else []:  # 红线关闭时（C33）红线证据不参与
        if e.excluded or (e.segment and e.segment in cfg.redlines.exclude_segments):
            continue
        if not _binary(e):
            continue
        thr = cfg.redlines.threshold_for(e.item_id)
        h = RedlineHit(
            redline_id=e.item_id, evidence_id=e.evidence_id, quote=e.quote, start_ms=e.start_ms, end_ms=e.end_ms,
            confidence=e.confidence, threshold=thr, reason=e.reason,
        )
        # 人工改判的证据以人工结论为准，不再比较模型置信度（decisions.md I7）
        if e.review.status == "overridden" or e.confidence >= thr:
            hits.append(h)
        else:
            below.append(h)

    redlines_done = (not cfg.redlines.enabled) or "redlines" in ctx.completed_detectors
    all_dims = all(d.status == "scored" for d in dims)
    status = "complete" if all_dims and redlines_done else "incomplete"
    threshold = cfg.thresholds[ctx.audience]
    total, grade_pass, critical = total_verdict(cfg, dims, threshold)
    missing = [i.item_id for i in items if i.status == "missing_evidence"]
    awaiting = [i.item_id for i in items if i.status == "awaiting_human"]
    if not redlines_done:
        missing.append("redlines")
    return RoundResult(
        rubric_version=cfg.version,
        config_hash=config_hash(cfg),
        status=status,
        items=items,
        dimensions=dims,
        total_grade=total,
        audience=ctx.audience,
        threshold=threshold,
        grade_pass=grade_pass,
        critical=critical,
        redlines_enabled=cfg.redlines.enabled,
        redlines_completed=redlines_done,
        redline_hits=hits,
        redline_below_threshold=below,
        missing_items=missing,
        low_confidence_items=[i.item_id for i in items if i.low_confidence],
        model_manifest=dict(ctx.model_manifest),
        awaiting_human_items=awaiting,
    )
