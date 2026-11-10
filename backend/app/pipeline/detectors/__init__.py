"""检测器注册表：条目编号 → 检测函数。每个函数只返回证据；抛异常即该检测器失败（缺失证据，不当作零次）。"""
from . import logic_other as lo
from . import persona as p
from . import sales as s
from .redlines import redlines

DETECTORS = {
    "P1": p.p1, "P2": p.p2, "P3": p.p3, "P4": p.p4, "P5": p.p5, "P6": p.p6, "P7": p.p7, "P8": p.p8, "P9": p.p9, "P10": p.p10,
    "S1": s.s1, "S2": s.s2, "S3": s.s3, "S4": s.s4,
    "L1": lo.l1, "L2": lo.l2, "L3": lo.l3, "L4": lo.l4, "L5": lo.l5,
    "O1": lo.o1, "O2": lo.o2, "O3": lo.o3, "O4": lo.o4,
    "redlines": redlines,
}
NEEDS_PROPS = {"P9"}


# 各检测器产出的证据对应的计分类型（证据协议）。评分配置的条目类型对不上时不能用于处理。
EVIDENCE_TYPES = {
    "P1": "T1", "P2": "T1", "P3": "T1", "P4": "T5", "P5": "T4", "P6": "T4", "P7": "T4", "P8": "T1", "P9": "T2", "P10": "T1",
    "S1": "T4", "S2": "T4", "S3": "T6", "S4": "T2",
    "L1": "T4", "L2": "T2", "L3": "T1", "L4": "T2", "L5": "T2",
    "O1": "T2", "O2": "T2", "O3": "T2", "O4": "T4",
}


def unsupported_items(cfg) -> list[str]:
    """评分配置里与检测器证据协议对不上的条目。检测器按评分表 20261105 改写（rubric-v0.2 起）；
    旧版 rubric-v0.1（卖点卡 + 结构、O5 保险知识、P3 评测分分档等）和 rubric-v0.2（P2 只计前 10 分钟）只能查看已有报告，不能用于新的处理。"""
    out = []
    for _, it in cfg.items():
        want = EVIDENCE_TYPES.get(it.id)
        if want is None:
            out.append(f"{it.id}（没有检测器）")
        elif it.type != want:
            out.append(f"{it.id}（配置为 {it.type}，检测器产出 {want} 证据）")
        elif it.id == "P2" and not (it.normalize and it.normalize.enabled and it.normalize.both_ways):
            # rubric-v0.3 起不截取前 10 分钟（C36）：检测器对整段主体段计次，配置须按时长双向换算，否则长视频会被多扣
            out.append("P2（检测器按整段主体段计次，配置须开启 normalize.both_ways 按每 10 分钟换算）")
    return out


# 各检测器依赖的模型能力（语音识别是所有条目的前提，不在此列）。某能力未配置时，依赖它的条目转评委打分。
CAPABILITIES = {
    "P1": {"vision"}, "P2": {"llm"}, "P3": {"speech_eval"}, "P4": set(), "P5": {"voice"}, "P6": {"voice"}, "P7": {"voice"},
    "P8": {"vision"}, "P9": {"vision"}, "P10": {"laugh", "llm"},
    "S1": {"llm"}, "S2": {"llm"}, "S3": {"llm"}, "S4": {"llm"},
    "L1": {"llm"}, "L2": {"llm"}, "L3": {"llm"}, "L4": {"llm"}, "L5": {"llm"},
    "O1": {"llm"}, "O2": {"llm"}, "O3": {"llm"}, "O4": {"llm"},
    "redlines": {"llm"},
}


def unavailable_capabilities(providers) -> set[str]:
    from ...providers.registry import Unavailable

    return {c for c in ("asr", "speech_eval", "llm", "vision", "laugh", "voice") if isinstance(getattr(providers, c), Unavailable)}


def human_plan(dcfg, providers, item_ids: set[str]) -> dict:
    """本次处理的人工打分分工：manual（只由评委打分，不跑检测器）、confirm、confirm_on_deduction、fallback。"""
    hr, missing = dcfg.human_review, unavailable_capabilities(providers)
    by_cap = {i for i in item_ids if CAPABILITIES.get(i, set()) & missing}
    return {"manual": sorted((set(hr.manual) | by_cap) & item_ids), "confirm": sorted(set(hr.confirm) & item_ids),
            "confirm_on_deduction": sorted(set(hr.confirm_on_deduction) & item_ids), "fallback": hr.fallback,
            "unavailable": sorted(missing)}
