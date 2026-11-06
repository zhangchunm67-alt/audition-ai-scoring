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
    旧版 rubric-v0.1（卖点卡 + 结构、O5 保险知识、P3 评测分分档等）只能查看已有报告，不能用于新的处理。"""
    out = []
    for _, it in cfg.items():
        want = EVIDENCE_TYPES.get(it.id)
        if want is None:
            out.append(f"{it.id}（没有检测器）")
        elif it.type != want:
            out.append(f"{it.id}（配置为 {it.type}，检测器产出 {want} 证据）")
    return out
