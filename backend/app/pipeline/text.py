"""逐字稿处理：分句、原句定位到时间、按读音计字数（P4）。时间均为整段视频毫秒（I11）。"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..providers.base import Word

SENT_END = set("。！？!?；;")
PUNCT = set("，,。！？!?；;：:、“”\"'‘’（）()…—- \n")
_CJK = re.compile(r"[一-鿿]")


@dataclass
class SegmentText:
    segment: str
    words: list[Word]  # 每个 Word 是一个字或一个标点；时间已换算为视频时间

    @property
    def text(self) -> str:
        return "".join(w.text for w in self.words)

    @property
    def start_ms(self) -> int:
        return self.words[0].start_ms if self.words else 0

    def span(self, i: int, j: int) -> tuple[int, int]:
        """字符区间 [i, j) 的起止时间。"""
        offsets = self._offsets()
        wi = offsets[i]
        wj = offsets[max(i, j - 1)]
        return self.words[wi].start_ms, self.words[wj].end_ms

    def _offsets(self) -> list[int]:
        out: list[int] = []
        for k, w in enumerate(self.words):
            out.extend([k] * len(w.text))
        return out

    def window(self, start_ms: int, end_ms: int) -> "SegmentText":
        return SegmentText(self.segment, [w for w in self.words if start_ms <= w.start_ms < end_ms])

    def min_confidence(self, i: int, j: int) -> float:
        offsets = self._offsets()
        ks = {offsets[x] for x in range(i, min(j, len(offsets)))}
        return min((self.words[k].confidence for k in ks), default=1.0)


@dataclass
class Sentence:
    text: str
    start_ms: int
    end_ms: int
    segment: str
    char_start: int


def sentences(st: SegmentText) -> list[Sentence]:
    out: list[Sentence] = []
    text = st.text
    i = 0
    for j, ch in enumerate(text):
        if ch in SENT_END or j == len(text) - 1:
            raw = text[i: j + 1]
            stripped = raw.strip()
            if stripped:
                lead = len(raw) - len(raw.lstrip())
                a, b = st.span(i + lead, j + 1)
                out.append(Sentence(stripped, a, b, st.segment, i + lead))
            i = j + 1
    return out


def _norm(s: str) -> str:
    return "".join(ch for ch in s if ch not in PUNCT)


def locate(st: SegmentText, quote: str, *, after_ms: int | None = None) -> tuple[int, int] | None:
    """把模型引用的原句定位回逐字稿的时间。忽略标点差异；after_ms 用于从某时刻之后找。"""
    span = locate_chars(st, quote, after_ms=after_ms)
    return st.span(*span) if span is not None else None


def locate_chars(st: SegmentText, quote: str, *, after_ms: int | None = None) -> tuple[int, int] | None:
    """返回实际匹配的原文字符区间 [i, j)，供时间与置信度共用。"""
    if not quote:
        return None
    text = st.text
    idx_map = [k for k, ch in enumerate(text) if ch not in PUNCT]
    plain = "".join(text[k] for k in idx_map)
    q = _norm(quote)
    if not q:
        return None
    pos = plain.find(q)
    while pos != -1:
        i, j = idx_map[pos], idx_map[pos + len(q) - 1] + 1
        a, _ = st.span(i, j)
        if after_ms is None or a >= after_ms:
            return i, j
        pos = plain.find(q, pos + 1)
    return None


# ───────────── 字数（数字按读出的字数计，P4） ─────────────

_DIG = "零一二三四五六七八九"


def _read_group(part: int) -> str:
    units = ["", "十", "百", "千"]
    s, zero = "", False
    for k in range(3, -1, -1):
        d = part // 10**k % 10
        if d:
            s += ("零" if zero and s else "") + _DIG[d] + units[k]
            zero = False
        elif s:
            zero = True
    return s


def _read_int(n: int) -> str:
    if n == 0:
        return "零"
    groups = []
    while n > 0:
        groups.append(n % 10000)
        n //= 10000
    out = ""
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if g == 0:
            continue
        if out and (g < 1000 or groups[i + 1] == 0):  # 低位组不足千位，或中间整组为零，补“零”
            out += "零"
        out += _read_group(g) + ["", "万", "亿"][i]
    return out[1:] if out.startswith("一十") else out


_NUM = re.compile(r"(\d+(?:\.\d+)?)(%?)(年?)")


def spoken(text: str) -> str:
    """把阿拉伯数字换成读法：4 位以上紧跟“年”的逐位读（年份），其他按数值读；百分号读作“百分之”。"""

    def repl(m: re.Match) -> str:
        num, pct, year = m.groups()
        if year and len(num) >= 4 and "." not in num:
            return "".join(_DIG[int(d)] for d in num) + "年"
        if "." in num:
            a, b = num.split(".", 1)
            s = _read_int(int(a)) + "点" + "".join(_DIG[int(d)] for d in b)
        else:
            s = _read_int(int(num))
        return ("百分之" + s if pct else s) + year

    return _NUM.sub(repl, text)


def char_count(text: str) -> int:
    """逐字稿汉字数（数字按读出的字数计）。"""
    return len(_CJK.findall(spoken(text)))
