"""提示词注入的前置检查（全面审查安全性第 1 条）：主播讲话里出现针对评分的话时，不交给模型自己判断，
而是把依赖大模型或视觉模型的条目全部转为评委确认（decisions.md T43）。

只查“针对评分系统”的说法，正常的保险讲解不会出现；宁可多转人工，不让一句话改了分。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

PATTERNS = [
    r"满分",
    r"(给|打|评)(我|她|他|本条|这条|这一条|这一项|这项)?(个|一个)?(高分|最高分|好评|一百分|100分)",
    r"评分(助手|系统|规则|标准|模型|机器人|程序)",
    r"(忽略|无视|忘掉|忘记)(掉)?(以上|之前|前面|上述|上面|所有|全部)",
    r"系统提示|提示词|系统指令|以下指令|新的指令",
    r"(以上|上面|刚才|前面)(的)?(都)?(是|为|只是)测试",
    r"(你|您)(现在)?是(一个|一名)?(AI|人工智能|大模型|评分|机器人|语言模型)",
    r"(AI|人工智能|大模型|模型)(请|你|您)",
    r"ignore (all|any|the|previous|above)|system prompt|you are now|full marks|score of 100",
]
_RE = re.compile("|".join(f"(?:{p})" for p in PATTERNS), re.IGNORECASE)


@dataclass
class Signal:
    segment: str
    quote: str
    at_ms: int | None


def scan(texts) -> list[Signal]:
    """texts：{分段: SegmentText}。返回命中的位置和前后各 10 个字。"""
    out: list[Signal] = []
    for name, st in texts.items():
        text = st.text
        for m in _RE.finditer(text):
            a, b = max(0, m.start() - 10), min(len(text), m.end() + 10)
            at = st.span(m.start(), m.end())[0] if text else None
            out.append(Signal(name, text[a:b], at))
    return out[:20]
