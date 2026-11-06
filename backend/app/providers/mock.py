"""Mock 实现：没有密钥也能端到端跑通。行为是确定的（同样输入同样输出），可注入延迟、失败和逐轮差异，供测试和压测用。

剧本（scenario）决定 Mock 语音识别“听到”什么：
- standard：一段完整的少儿医疗险试镜，含口头禅、四条异议的回答、促成、结构化表达等
- redline：在 standard 基础上加入“稳赚不赔”“加我微信单独聊”
"""
from __future__ import annotations

import random
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field

from ..pipeline import prompts
from .base import Frame, LaughCandidate, ProviderError, SegmentHint, SpeechEvalResult, TranscriptResult, VisionFinding, VoiceRating, Word

OPENING = "家里有孩子的家长先别走，今天讲清楚一件事：孩子看病，医保报完剩下的钱怎么报。"
PITCH = (
    "那么我们来看一下这个产品。孩子一年感冒发烧要跑好几趟医院，医保报完，自费药、进口药这部分还得自己掏。"
    "这款产品就三个好：保得全、报得多、价格低。先说保得全，保障范围包括门急诊和住院。"
    "再说报得多，报销比例是百分之百。免赔额，就是先自己掏的那部分钱，超过的才给报，这款免赔额是零元。"
    "最后说价格，一年三百六十五元，平均每天不到一块钱。所以小病大病都有覆盖。"
    "给大家做一个讲解，这是一个非常好的一个产品。等待期，就是合同生效后的一段观察期，这款等待期是三十天。"
    "儿童医院可以用，门急诊不限次数，雾化可以报。带孩子去缴费，不用盯着收费员看哪些是医保内、哪些是医保外。"
    "健康告知请如实填写。续保条件是每年审核续保。责任免除部分请大家仔细看条款，懂了吗？"
)
REDLINE_EXTRA = "这款产品稳赚不赔，想了解的加我微信单独聊。"
ANSWERS = {
    "孩子有医保了，还需要买吗？": "孩子有医保了还需要买吗？需要。医保有报销范围和比例限制，医保外的部分要自己付。这款能报医保外的自费部分。先看看家里现有的保障，缺这块再补。",
    "之前得过肺炎，还能买吗？": "之前得过肺炎还能买吗？以健康告知为准，请如实告知，有疑问走人工核保。这款健康告知比较清楚。先对照一下健康告知，符合再给孩子安排。",
    "这么便宜，理赔会不会很难？": "这么便宜理赔会不会很难？不会。理赔按合同条款和流程办理。承保公司是正规的保险公司。有疑问可以先看理赔流程说明。",
    "为什么比别家贵？": "为什么比别家贵？我们客观对比条款差异，这款保障范围更全。上个月有一百二十位家长给孩子投了这款。对照条款选适合自家的。",
}
GENERIC_ANSWER = "这个问题问得好。我们按条款来看，这款产品有相应的保障。大家可以先对照条款再决定。"
QA = {
    "什么是等待期": "等待期是合同生效后的一段时间，天数以条款为准。这段时间内因疾病出险不赔，意外导致的一般不受等待期限制。",
    "医疗险和重疾险有什么区别": "医疗险按实际花费报销，重疾险确诊约定疾病后一次性给付。医疗险管医疗费用，重疾险可以弥补收入损失和康复费用，两者是互补关系。",
}
GENERIC_QA = "这个我理解是先自己承担一部分，具体以条款为准。"


def _duration_ms(path: str) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout.strip()
    return int(float(out) * 1000)


@dataclass
class Faults:
    """注入延迟和失败（压测和重试测试用）。fail_times：前 N 次调用失败。"""

    latency_s: float = 0.0
    fail_times: int = 0
    fail_rate: float = 0.0
    seed: int = 0
    _calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def hit(self, what: str) -> None:
        with self._lock:
            self._calls += 1
            n = self._calls
        if self.latency_s:
            time.sleep(self.latency_s)
        if n <= self.fail_times or (self.fail_rate and random.Random(self.seed * 100003 + n).random() < self.fail_rate):
            raise ProviderError(f"{what}：模拟供应商错误（第 {n} 次调用）")


def _spread(text: str, start: int, end: int, conf: float = 0.95) -> list[Word]:
    """把一段文字均匀铺到 [start, end) 里，句末留 0.4 秒停顿。"""
    chars = list(text)
    if not chars:
        return []
    pauses = sum(1 for c in chars if c in "。！？")
    span = max(1, end - start - pauses * 400)
    step = span / len(chars)
    out, t = [], float(start)
    for c in chars:
        a = int(t)
        t += step
        out.append(Word(c, a, max(a + 1, int(t)), conf))
        if c in "。！？":
            t += 400
    return out


class MockASR:
    name, model_version = "mock-asr", "1"

    def __init__(self, scenario: str = "standard", faults: Faults | None = None, rtf: float = 0.0):
        """rtf：模拟识别耗时 = 音频时长 × rtf（压测用）。"""
        self.scenario, self.faults, self.rtf = scenario, faults or Faults(), rtf

    def transcribe(self, audio_path: str, *, disfluency_removal: bool, word_timestamps: bool, hint: SegmentHint) -> TranscriptResult:
        if disfluency_removal or not word_timestamps:
            raise ProviderError("必须关闭顺滑并返回字级时间戳")
        dur = _duration_ms(audio_path)
        if self.rtf:
            time.sleep(dur / 1000 * self.rtf)
        self.faults.hit("语音识别")
        if hint.segment == "main":
            pitch = PITCH + (REDLINE_EXTRA if self.scenario == "redline" else "")
            opening_end = min(dur, 30_000) if dur > 40_000 else dur // 8
            cuts = [o for o in hint.objection_offsets_ms if opening_end < o < dur]
            words = _spread(OPENING, 0, opening_end)
            words += _spread(pitch, opening_end + 300, (cuts[0] if cuts else dur) - 300)
            texts = hint.objection_texts
            for i, at in enumerate(cuts):
                nxt = cuts[i + 1] if i + 1 < len(cuts) else dur
                ans = ANSWERS.get(texts[i] if i < len(texts) else "", GENERIC_ANSWER)
                words += _spread(ans, at + 1500, nxt - 300)  # 弹出后 1.5 秒开始回应
        elif hint.segment == "reading":
            words = _spread(hint.reading_text or "", 300, dur - 300)
        else:
            q = (hint.question_text or "").rstrip("？?")
            ans = next((v for k, v in QA.items() if k in q), GENERIC_QA)
            words = _spread(ans, 500, dur - 300)
        return TranscriptResult(words, self.name, self.model_version, {"disfluency_removal": False, "word_timestamps": True})


class MockSpeechEval:
    """朗读段评测：按参考文本均匀标出 dialect 处方言、mispronounce 处发音不准（时间按朗读稿铺满音频估算）。"""

    name, model_version = "mock-speech-eval", "1"

    def __init__(self, score: float = 86.0, dialect: int = 1, mispronounce: int = 1, faults: Faults | None = None):
        self.score, self.dialect, self.mispronounce, self.faults = score, dialect, mispronounce, faults or Faults()

    def assess(self, audio_path: str, reference_text: str) -> SpeechEvalResult:
        if not reference_text:
            raise ProviderError("普通话评测需要参考文本")
        self.faults.hit("语音评测")
        dur = _duration_ms(audio_path)
        n = self.dialect + self.mispronounce
        step = len(reference_text) / (n + 1)
        per_char = max(1, (dur - 600) / max(1, len(reference_text)))
        errors = []
        for i in range(n):
            pos = int(step * (i + 1))
            a = int(300 + pos * per_char)
            errors.append({"text": reference_text[pos], "start_ms": a, "end_ms": a + int(per_char), "confidence": 0.8,
                           "type": "dialect" if i < self.dialect else "mispronounce"})
        return SpeechEvalResult(self.score, {"reference_chars": len(reference_text), "errors": errors}, self.name, self.model_version)


class MockVision:
    name, model_version = "mock-vision", "1"

    def __init__(self, attire_issues: tuple[str, ...] = (), fidgets: int = 0, faults: Faults | None = None):
        """attire_issues：模拟不符合要求的项（"attire" 穿着、"hairstyle" 发型）。"""
        self.attire_issues, self.fidgets, self.faults = attire_issues, fidgets, faults or Faults()

    def analyze(self, task: str, frames: list[Frame], context: dict) -> list[VisionFinding]:
        self.faults.hit("视觉")
        if not frames:
            return []
        if task == "attire":
            a, b = frames[0].at_ms, frames[-1].at_ms
            out = [VisionFinding(a, b, lab, "count", 0.8, f"{'穿着' if lab == 'attire' else '发型'}不符合要求（模拟）")
                   for lab in self.attire_issues]
            for lab in ("attire", "hairstyle"):
                if lab not in self.attire_issues:
                    out.append(VisionFinding(a, b, lab, "not_count", 0.8, f"{'穿着' if lab == 'attire' else '发型'}符合要求（模拟）"))
            return out
        if task == "fidget":
            step = max(1, len(frames) // (self.fidgets + 1))
            return [VisionFinding(f.at_ms, f.at_ms + 1000, "touch_face", "count", 0.75, "手接近面部（模拟）") for f in frames[step::step][: self.fidgets]]
        if task == "prop_pointing":
            return [VisionFinding(at, at + 1000, "sticker", "count", 0.7, "手指向贴片（模拟）") for at in context.get("guide_ms", [])]
        return []


class MockVoice:
    """声音主观评价的 Mock：按本地声学特征给一个确定的分，只用来跑通流程，不代表真实评价。"""

    name, model_version = "mock-voice", "1"

    def __init__(self, scores: dict[str, int] | None = None, faults: Faults | None = None):
        self.scores, self.faults = scores or {}, faults or Faults()

    def rate(self, audio_path: str, aspect: str, *, criterion: str, max_score: int, context: dict) -> VoiceRating:
        self.faults.hit("声音评价")
        if aspect in self.scores:
            score = self.scores[aspect]
        elif aspect == "rhythm":
            score = max(0, max_score - 2 * int(context.get("stall_count", 0)) - int(context.get("run_on_count", 0)))
        else:
            score = max_score - 1 if context.get("pitch_range_st", 0) >= 4 else max_score // 2
        return VoiceRating(score=min(max_score, max(0, score)), confidence=0.7, reason=f"{criterion}（模拟评价）")


class MockLaugh:
    name, model_version = "mock-laugh", "1"

    def __init__(self, faults: Faults | None = None):
        self.faults = faults or Faults()

    def detect(self, audio_path: str) -> list[LaughCandidate]:
        self.faults.hit("笑声检测")
        return []


def _has(text: str, *keys: str) -> bool:
    return any(k in text for k in keys)


def _sents(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[。！？；])", text) if s.strip()]


class MockLLM:
    """按任务做关键词规则判断，返回与真实模型相同结构的 JSON。round_overrides 可让某一轮给出不同结果（测临界三轮）。"""

    name, model_version = "mock-llm", "1"

    def __init__(self, faults: Faults | None = None, round_overrides: dict | None = None):
        self.faults = faults or Faults()
        self.round_overrides = round_overrides or {}

    def complete_json(self, task: str, system: str, user: str, schema: dict, *, temperature: float, payload: dict) -> dict:
        if temperature != 0:
            raise ProviderError("v1 所有大模型调用必须温度 0")
        self.faults.hit("大模型")
        override = self.round_overrides.get((payload.get("_round"), task))
        if override is not None:
            return override(payload) if callable(override) else override
        out = getattr(self, f"_{task}")(payload)
        prompts.TASKS[task][1].model_validate(out)  # 与真实模型同样校验
        return out

    # —— 各任务 ——
    def _p2_filler(self, p):
        items = []
        for c in p["candidates"]:
            s, w = c["sentence"], c["word"]
            keep = not (
                (w == "一个" and re.search(r"一个(孩子|月|人|家庭|问题)", c["context"]))
                or (w in ("的话",) and "有医保的话" in c["context"])
                or (w == "那么" and "既然" in s)
            )
            items.append({"id": c["id"], "count": keep, "reason": "删掉后意思不变" if keep else "承担实义", "confidence": 0.86})
        return {"items": items}

    def _p10_laugh(self, p):
        return {"items": [{"id": c["id"], "count": True, "reason": "与内容无关的笑场", "confidence": 0.7} for c in p["candidates"]]}

    def _s1_need(self, p):
        t = p["transcript"]
        risk, gap, link = _has(t, "感冒发烧", "风险", "看病"), _has(t, "自己掏", "自费", "缺口"), _has(t, "这款")
        level = 9 if risk and gap and link else 5 if (risk or gap) else 0
        quote = next((s for s in _sents(t) if "自己掏" in s or "感冒发烧" in s), "")
        return {"level": level, "quote": quote, "reason": "风险→缺口→产品", "confidence": 0.82}

    def _s2_fixed_script(self, p):
        """按固定话术逐句看逐字稿里有没有讲到（取句子前 6 个字匹配），按完成比例给分；“没有等待期”记为讲错。"""
        t = p["transcript"]
        script = [x for x in _sents(p["fixed_script"]) if x.strip()]
        done = [x for x in script if x[:6] in t]
        errors = [{"quote": s, "reason": "与固定话术、条款不符", "confidence": 0.8} for s in _sents(t) if "没有等待期" in s]
        score = round(p["max_score"] * len(done) / len(script)) if script else 0
        score = max(0, score - 5 * len(errors))
        quote = next((s for s in _sents(t) if any(x[:6] in s for x in done)), "")
        return {"score": score, "quote": quote if score else "", "reason": f"固定话术 {len(done)}/{len(script)} 句讲到",
                "confidence": 0.8, "errors": errors}

    def _s3_objection(self, p):
        t = p["transcript_after"]
        first = _sents(t)[:3]
        head = "".join(first)
        answered = bool(t.strip()) and _has(head, "需要", "不会", "能", "以健康告知为准", "对比", "条款")
        return {
            "answered": answered,
            "direct_answer": answered and _has(head, "需要", "不会", "以健康告知为准", "对比", "能"),
            "advantage": answered and _has(t, "这款"),
            "altruistic_close": answered and _has(t, "先看看", "先对照", "选适合", "可以先看"),
            "wrong": _has(t, "随便买", "随便填"),
            "quote": head, "reason": "按回答内容判断", "confidence": 0.8,
        }

    def _s4_closing(self, p):
        rules = [("herd", ("位家长",), True), ("loss_aversion", ("还得自己掏", "自己付"), True), ("authority", ("承保公司",), True),
                 ("price_split", ("每天不到",), True), ("sunk_cost", ("看了这么久",), True), ("herd", ("全网都在抢",), False),
                 ("loss_aversion", ("最后10单", "最后十单", "最后几单", "明天停售"), False), ("authority", ("国家推荐",), False)]
        items = []
        for s in _sents(p["transcript"]):
            for method, keys, ok in rules:
                if _has(s, *keys):
                    items.append({"method": method, "compliant": ok, "quote": s, "reason": "合规写法" if ok else "施压或虚构", "confidence": 0.8})
        return {"items": items}

    def _l1_opening(self, p):
        t = p["opening"]
        what, who, hook = _has(t, "今天讲", "讲清楚"), _has(t, "家长", "有孩子"), _has(t, "先别走", "讲清楚")
        n = sum([what, who, hook])
        level = [0, 8, 13, 18][n] if t.strip() else 0
        return {"level": level, "quote": _sents(t)[0] if t else "", "reason": f"讲什么、对谁、为什么现在听 {n}/3", "confidence": 0.85}

    def _founds(self, t, pred, label=lambda s: ""):
        return {"items": [{"quote": s, "valid": True, "label": label(s), "reason": "符合", "confidence": 0.8} for s in _sents(t) if pred(s)]}

    def _l2_structure(self, p):
        return self._founds(p["transcript"], lambda s: "就三个好" in s)

    def _l3_deduction(self, p):
        out = self._founds(p["transcript"], lambda s: "都必须" in s or "一定要买" in s)
        for it in out["items"]:
            it["valid"] = False
        return out

    def _l4_induction(self, p):
        return self._founds(p["transcript"], lambda s: s.count("、") in (2, 3) and "：" in s)

    def _l5_facts(self, p):
        return self._founds(p["transcript"], lambda s: _has(s, "免赔额是", "等待期是", "报销比例是"), lambda s: re.sub(r"是.*", "", s)[-3:])

    def _o1_terms(self, p):
        items = []
        for g in p["glossary"]:
            s = next((x for x in _sents(p["transcript"]) if g["term"] in x and "就是" in x), None)
            if s:
                items.append({"quote": s, "valid": True, "label": g["term"], "reason": "紧跟白话解释", "confidence": 0.85})
        return {"items": items}

    def _o2_targeted(self, p):
        items = []
        for pt in p["targeted_points"]:
            key = pt[:4]
            s = next((x for x in _sents(p["transcript"]) if key in x), None)
            if s:
                items.append({"quote": s, "valid": True, "label": pt, "reason": "针对痛点", "confidence": 0.8})
        return {"items": items}

    def _o3_scene(self, p):
        return self._founds(p["transcript"], lambda s: _has(s, "带孩子去", "收费员"))

    def _o4_control(self, p):
        m = p["measured"]
        returned = sum(1 for x in p["segments_after_objection"] if x["text"].strip())
        level = 20 - 3 * int(m["unanswered_objections"]) - 2 * int(m["dead_air_count"]) - (len(p["segments_after_objection"]) - returned)
        if m["loudness_range_db"] < 5:
            level -= 3
        return {"level": max(0, min(20, level)), "quote": "", "reason": f"回到主线 {returned}/{len(p['segments_after_objection'])}",
                "confidence": 0.75}

    def _rewrite(self, p):
        s = p["sentence"]
        for w in ("那么，", "那么", "这边给你", "什么呀", "，懂了吗", "懂了吗", "，对不对", "对不对"):
            s = s.replace(w, "")
        s = re.sub(r"一个(非常好的)一个", r"一个\1", s).replace("做一个讲解", "讲解")
        if s == p["sentence"]:
            s = s.rstrip("。！？") + "（以条款为准）。"
        return {"suggestion": s, "reason": "去掉口头禅，表述更准确", "confidence": 0.7}

    def _redline_judge(self, p):
        return {"items": [{"id": c["id"], "hit": not _has(c["sentence"], "不能说", "不是"), "confidence": 0.9, "reason": "命中典型说法"} for c in p["candidates"]]}
