"""兼容 OpenAI 接口的模型服务：本地 llama.cpp 的 llama-server、Ollama、LM Studio，或云端兼容接口。
用于在 Mac Studio 上本地部署千问：
- OpenAICompatLLM：大模型判断（文本模型，如 Qwen3 30B-A3B），按 JSON Schema 约束输出；
- OpenAICompatVision：P1 着装 / P8 小动作 / P9 道具（视觉模型，如 Qwen3-VL），图片以 data URL 发送；
- OpenAICompatVoice：P5 语调 / P6 音色 / P7 节奏（能听音频的模型，如 Qwen3-Omni），截取若干片段分别打分取中位数。

只用标准库发 HTTP 请求。模型须在 macOS 上原生运行（Docker 里用不了 Apple GPU），容器内用 http://host.docker.internal:端口/v1 访问。
"""
from __future__ import annotations

import base64
import io
import json
import re
import statistics
import urllib.error
import urllib.request
import wave
from typing import Any

from .base import Frame, ProviderError, VisionFinding, VoiceRating

_THINK = re.compile(r"<think>.*?</think>", re.S)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def parse_json(text: str) -> Any:
    """取模型回复里的 JSON：去掉思考段和代码块围栏。"""
    t = _FENCE.sub("", _THINK.sub("", text or "").strip()).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        a, b = t.find("{"), t.rfind("}")
        if a >= 0 and b > a:
            try:
                return json.loads(t[a: b + 1])
            except json.JSONDecodeError:
                pass
    raise ProviderError(f"模型没有返回合法 JSON：{t[:200]!r}")


class _Client:
    def __init__(self, base_url: str, model: str, *, api_key: str | None = None, timeout_s: float = 600,
                 json_mode: str = "json_schema", extra: dict | None = None):
        self.base_url, self.model, self.api_key, self.timeout_s = base_url.rstrip("/"), model, api_key, timeout_s
        self.json_mode, self.extra = json_mode, extra or {}
        self.name, self.model_version = "openai-compat", model

    def chat(self, messages: list[dict], *, temperature: float, schema: dict | None, name: str) -> Any:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": temperature, **self.extra}
        if self.json_mode == "json_schema" and schema is not None:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": name, "schema": schema}}
        elif self.json_mode in ("json_schema", "json_object"):
            body["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(body, ensure_ascii=False).encode(),
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"模型服务返回 {exc.code}：{exc.read()[:300]!r}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"连不上模型服务 {self.base_url}：{exc}") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"模型服务返回格式不对：{str(data)[:300]}") from exc
        return parse_json(content)


class OpenAICompatLLM(_Client):
    def complete_json(self, task: str, system: str, user: str, schema: dict, *, temperature: float, payload: dict) -> dict:
        out = self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                        temperature=temperature, schema=schema, name=task)
        if not isinstance(out, dict):
            raise ProviderError(f"{task}: 模型返回的不是 JSON 对象")
        return out


def _image_part(path: str) -> dict:
    with open(path, "rb") as fh:
        return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(fh.read()).decode()}}


def _judged(v: dict) -> tuple[bool, str, float]:
    return bool(v.get("flag")), str(v.get("reason", "")), float(min(1.0, max(0.0, v.get("confidence", 0.5))))


VISION_SYSTEM = "你是保险直播主播试镜的评分助手，只根据给定画面判断，不评价相貌、身材、年龄、性别等个人特征。严格按要求输出 JSON。"
FRAME_FLAGS = {
    "type": "object", "required": ["frames"],
    "properties": {"frames": {"type": "array", "items": {"type": "object", "required": ["index", "flag"], "properties": {
        "index": {"type": "integer"}, "flag": {"type": "boolean"}, "label": {"type": "string"},
        "reason": {"type": "string"}, "confidence": {"type": "number"}}}}},
}
ATTIRE = {
    "type": "object", "required": ["attire", "hairstyle"],
    "properties": {k: {"type": "object", "required": ["flag"], "properties": {
        "flag": {"type": "boolean"}, "reason": {"type": "string"}, "confidence": {"type": "number"}}} for k in ("attire", "hairstyle")},
}


class OpenAICompatVision(_Client):
    """视觉判断。dress_code 为着装发型要求的文字说明（评分表未写明，P-P1-DRESS），由培训提供后通过环境变量传入。"""

    def __init__(self, *a, dress_code: str = "", attire_max_frames: int = 6, batch: int = 8, **kw):
        super().__init__(*a, **kw)
        self.dress_code, self.attire_max_frames, self.batch = dress_code, attire_max_frames, batch

    def analyze(self, task: str, frames: list[Frame], context: dict) -> list[VisionFinding]:
        if not frames:
            return []
        if task == "attire":
            return self._attire(frames)
        if task == "fidget":
            return self._per_frame(frames, "fidget",
                                   "逐帧判断主播是否有与讲解无关的小动作（摸脸、摸头发、玩笔、频繁晃动身体、频繁低头看稿等）。"
                                   "有则 flag=true，label 填动作英文简称（如 touch_face、touch_hair、play_pen、sway、look_down）。")
        if task == "prop_pointing":
            return self._per_frame(frames, "prop",
                                   "逐帧判断主播是否正在用手或道具指向画面里的贴片或 KT 板讲解。"
                                   "是则 flag=true，label 填 sticker（贴片）或 kt_board（KT 板）。")
        raise ProviderError(f"不支持的视觉任务 {task}")

    def _attire(self, frames: list[Frame]) -> list[VisionFinding]:
        step = max(1, len(frames) // self.attire_max_frames)
        picked = frames[::step][: self.attire_max_frames]
        rule = self.dress_code or "保险直播主播的职业形象：着装整洁得体、适合直播讲解；发型整齐（具体要求待培训提供）"
        text = (f"以下是同一位主播在试镜中不同时间的 {len(picked)} 帧画面。按要求判断穿着、发型是否**不符合**要求"
                f"（不符合则 flag=true）。要求：{rule}。只看穿着和发型，不评价相貌。按 JSON Schema 输出：{json.dumps(ATTIRE, ensure_ascii=False)}")
        out = self.chat([{"role": "system", "content": VISION_SYSTEM},
                         {"role": "user", "content": [{"type": "text", "text": text}, *[_image_part(f.path) for f in picked]]}],
                        temperature=0, schema=ATTIRE, name="attire")
        a, b = frames[0].at_ms, frames[-1].at_ms
        res = []
        for lab in ("attire", "hairstyle"):
            if lab not in out:
                raise ProviderError(f"着装判断缺少 {lab}")
            flag, reason, conf = _judged(out[lab])
            res.append(VisionFinding(a, b, lab, "count" if flag else "not_count", conf, reason))
        return res

    def _per_frame(self, frames: list[Frame], name: str, instruction: str) -> list[VisionFinding]:
        res = []
        for i in range(0, len(frames), self.batch):
            chunk = frames[i: i + self.batch]
            text = (f"{instruction}\n共 {len(chunk)} 帧，按顺序编号 0–{len(chunk) - 1}，每帧都要给出结果。"
                    f"按 JSON Schema 输出：{json.dumps(FRAME_FLAGS, ensure_ascii=False)}")
            out = self.chat([{"role": "system", "content": VISION_SYSTEM},
                             {"role": "user", "content": [{"type": "text", "text": text}, *[_image_part(f.path) for f in chunk]]}],
                            temperature=0, schema=FRAME_FLAGS, name=name)
            got = {int(x["index"]): x for x in out.get("frames", []) if isinstance(x, dict) and "index" in x}
            if set(got) != set(range(len(chunk))):
                raise ProviderError(f"视觉模型漏判了帧：{sorted(set(range(len(chunk))) - set(got))}")
            for k, f in enumerate(chunk):
                flag, reason, conf = _judged(got[k])
                if flag:
                    res.append(VisionFinding(f.at_ms, f.at_ms + 1000, str(got[k].get("label") or name), "count", conf, reason))
        return res


VOICE = {"type": "object", "required": ["score"], "properties": {
    "score": {"type": "integer"}, "reason": {"type": "string"}, "confidence": {"type": "number"}}}


def _clips(path: str, n: int, clip_s: float) -> list[bytes]:
    """均匀截取 n 段 clip_s 秒的 wav（整段音频较长时，长音频输入效果会下降，见 README）。"""
    with wave.open(path, "rb") as w:
        sr, total = w.getframerate(), w.getnframes()
        params = w.getparams()
        size = int(clip_s * sr)
        starts = [0] if total <= size else [int((total - size) * k / max(1, n - 1)) for k in range(n)]
        out = []
        for s in starts:
            w.setpos(s)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as o:
                o.setparams(params)
                o.writeframes(w.readframes(min(size, total - s)))
            out.append(buf.getvalue())
        return out


class OpenAICompatVoice(_Client):
    def __init__(self, *a, clips: int = 3, clip_s: float = 45.0, **kw):
        super().__init__(*a, **kw)
        self.clips, self.clip_s = clips, clip_s

    def rate(self, audio_path: str, aspect: str, *, criterion: str, max_score: int, context: dict) -> VoiceRating:
        scores, reasons, confs = [], [], []
        for k, clip in enumerate(_clips(audio_path, self.clips, self.clip_s)):
            text = (f"这是一位保险直播主播试镜讲解的一段录音（第 {k + 1} 段）。评分表条目：{criterion}，满分 {max_score}。"
                    f"只根据听到的声音表现打分，给出 0–{max_score} 的整数 score；不评价性别、年龄、地域等个人特征。"
                    f"参考测量值（整段）：{json.dumps(context, ensure_ascii=False)}。按 JSON Schema 输出：{json.dumps(VOICE, ensure_ascii=False)}")
            out = self.chat([{"role": "user", "content": [
                {"type": "input_audio", "input_audio": {"data": base64.b64encode(clip).decode(), "format": "wav"}},
                {"type": "text", "text": text}]}], temperature=0, schema=VOICE, name=f"voice_{aspect}")
            s = out.get("score")
            if isinstance(s, bool) or not isinstance(s, int) or not 0 <= s <= max_score:
                raise ProviderError(f"{aspect}: 模型给分 {s!r} 不是 0–{max_score} 的整数")
            scores.append(s)
            reasons.append(str(out.get("reason", "")))
            confs.append(float(min(1.0, max(0.0, out.get("confidence", 0.5)))))
        med = int(statistics.median_low(scores))
        return VoiceRating(med, round(min(confs), 3), f"各段得分 {scores}，取中位数 {med}；" + "；".join(r for r in reasons if r)[:300])
