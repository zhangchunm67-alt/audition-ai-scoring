"""检测器注册表：条目编号 → 检测函数。每个函数只返回证据；抛异常即该检测器失败（缺失证据，不当作零次）。"""
from . import logic_other as lo
from . import persona as p
from . import sales as s
from .redlines import redlines

DETECTORS = {
    "P1": p.p1, "P2": p.p2, "P3": p.p3, "P4": p.p4, "P5": p.p5, "P7": p.p7, "P8": p.p8, "P9": p.p9, "P10": p.p10,
    "S1": s.s1, "S2": s.s2, "S3": s.s3, "S4": s.s4,
    "L1": lo.l1, "L2": lo.l2, "L3": lo.l3, "L4": lo.l4, "L5": lo.l5,
    "O1": lo.o1, "O2": lo.o2, "O3": lo.o3, "O4": lo.o4, "O5": lo.o5,
    "redlines": redlines,
}
NEEDS_PROPS = {"P9"}
