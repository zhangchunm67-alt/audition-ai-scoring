"""多轮汇总、结论和标签。纯函数。

规则来源见 docs/decisions.md：C5（临界三轮）、C6（标签）、C11（跨轮红线、展示轮次）、I2（多数结论口径）。
"""
from __future__ import annotations

from .config import RubricConfig
from .types import LABEL_ZH, FinalVerdict, RoundResult, RoundSummary


class VerdictError(ValueError):
    pass


def rounds_required(first: RoundResult, cfg: RubricConfig) -> int:
    """首轮之后总共需要几轮。首轮不完整时无法判断，由流水线先重试首轮。"""
    if first.status != "complete":
        raise VerdictError("首轮不完整，不能判断是否临界；请先重试首轮（重试不算新的投票轮次）")
    return cfg.critical.total_rounds if first.critical else 1


def _summary(i: int, r: RoundResult) -> RoundSummary:
    return RoundSummary(
        round_no=i,
        total_grade=r.total_grade,  # type: ignore[arg-type]
        grade_pass=bool(r.grade_pass),
        redline_ids=sorted({h.redline_id for h in r.redline_hits}),
        dimension_scores={d.id: d.score for d in r.dimensions},  # type: ignore[misc]
        dimension_grades={d.id: d.grade for d in r.dimensions},  # type: ignore[misc]
    )


def finalize(rounds: list[RoundResult], cfg: RubricConfig) -> FinalVerdict:
    if not rounds:
        raise VerdictError("没有任何一轮结果")
    bad = [i + 1 for i, r in enumerate(rounds) if r.status != "complete"]
    if bad:
        missing = sorted({m for r in rounds for m in r.missing_items})
        return FinalVerdict(
            status="incomplete",
            rounds_received=len(rounds),
            message=f"第 {', '.join(map(str, bad))} 轮缺少必需证据：{'、'.join(missing)}；不出结论",
        )
    first = rounds[0]
    keys = {(r.rubric_version, r.config_hash, r.audience) for r in rounds}
    if len(keys) != 1:
        raise VerdictError("各轮使用的评分配置或达标线不一致")
    required = rounds_required(first, cfg)
    if len(rounds) < required:
        return FinalVerdict(
            status="needs_more_rounds",
            critical=True,
            rounds_required=required,
            rounds_received=len(rounds),
            message=f"临界样本，需共 {required} 轮，已有 {len(rounds)} 轮",
        )
    if len(rounds) > required:
        raise VerdictError(f"需要 {required} 轮，收到 {len(rounds)} 轮；追加轮次不递归")

    summaries = [_summary(i + 1, r) for i, r in enumerate(rounds)]
    votes = sum(1 for s in summaries if s.grade_pass)
    majority_pass = votes * 2 > len(summaries)
    # 展示轮：三轮总档位的中位数所在轮（同值取最早一轮）。中位数一定落在多数结论一侧。
    median_total = sorted(s.total_grade for s in summaries)[len(summaries) // 2]
    display = next(s for s in summaries if s.total_grade == median_total)
    assert display.grade_pass == majority_pass

    hits = [(i + 1, h) for i, r in enumerate(rounds) for h in r.redline_hits]
    redline = bool(hits)
    critical = bool(first.critical)
    conclusion = "pass" if majority_pass and not redline else "fail"
    if redline or conclusion == "fail":
        label = "not_recommend"
    elif critical:
        label = "pending"
    else:
        label = "recommend"

    thr = first.threshold
    t = display.total_grade
    vote_txt = f"{votes}/{len(summaries)} 轮总档位达标"
    if redline:
        rl = "、".join(f"{h.redline_id}（第 {n} 轮）" for n, h in hits)
        reason = f"命中合规红线 {rl}，结论为不达标"
        if critical:
            reason += f"；临界样本，{vote_txt}"
    elif conclusion == "fail":
        reason = f"总档位 {t}，未达到达标线（< {thr}）"
        if critical:
            reason += f"；临界样本，{vote_txt}"
    elif critical:
        reason = f"临界样本：总档位 {t} 接近达标线（< {thr}），{vote_txt}，请谨慎使用"
    else:
        reason = f"总档位 {t}，达到达标线（< {thr}），无红线"

    return FinalVerdict(
        status="complete",
        conclusion=conclusion,
        label=label,
        label_zh=LABEL_ZH[label],
        reason=reason,
        critical=critical,
        redline_hit=redline,
        redline_hits=hits,
        majority_grade_pass=majority_pass,
        display_round=display.round_no,
        rounds=summaries,
        rounds_required=required,
        rounds_received=len(rounds),
    )
