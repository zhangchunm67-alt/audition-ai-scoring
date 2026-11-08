"""离线判定文件（replay）：把大模型 / 视觉判断请求写成文件，由外部判定者（人工评审、另一个模型）作答后回放。

用途：
- 在还没有部署好本地千问时，先跑通真实录像的整条流水线（语音识别、分段、引用定位、计分）；
- 把一次判定结果固定下来，之后换成本地千问时，可以在同样的请求上逐条对比。

工作方式：每个请求按“任务 + 输入内容”算出键。answers/<键>.json 存在就直接返回；
不存在就写 pending/<键>.json（含提示词、输出结构和输入），本次调用失败（检测器失败、条目未评），作答后重跑即可。
回放结果和真实模型一样经过输出结构校验、引用定位，不会绕过任何检查。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .base import Frame, ProviderError, VisionFinding


def _key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]


class _Store:
    def __init__(self, root: str):
        self.root = Path(root)
        (self.root / "answers").mkdir(parents=True, exist_ok=True)
        (self.root / "pending").mkdir(parents=True, exist_ok=True)

    def get(self, key: str, request: dict):
        ans, pend = self.root / "answers" / f"{key}.json", self.root / "pending" / f"{key}.json"
        if ans.exists():
            pend.unlink(missing_ok=True)
            return json.loads(ans.read_text("utf-8"))
        pend.write_text(json.dumps(request, ensure_ascii=False, indent=1), "utf-8")
        raise ProviderError(f"待外部判定：{request.get('task')}（{key}），作答后写入 answers/{key}.json 再重跑")


class ReplayLLM:
    name, model_version = "replay-llm", "file"

    def __init__(self, root: str, judge: str = "external"):
        self.store, self.model_version = _Store(root), f"file:{judge}"

    def complete_json(self, task: str, system: str, user: str, schema: dict, *, temperature: float, payload: dict) -> dict:
        clean = {k: v for k, v in payload.items() if k != "_round"}  # 各轮输入相同则答案相同
        return self.store.get(_key("llm", task, clean), {"task": task, "system": system, "instruction": user.split("\n\n输入：")[0],
                                                       "payload": clean, "schema": schema})


class ReplayVision:
    """只回放指定的任务（tasks），其余任务视为未配置。answers 文件格式：[{at_ms, end_ms, label, judgment, confidence, reason}]。"""

    name, model_version = "replay-vision", "file"

    def __init__(self, root: str, tasks: set[str], judge: str = "external"):
        self.store, self.tasks, self.model_version = _Store(root), tasks, f"file:{judge}"

    def analyze(self, task: str, frames: list[Frame], context: dict) -> list[VisionFinding]:
        if task not in self.tasks:
            raise ProviderError(f"视觉任务 {task} 未配置判定方式")
        digest = [hashlib.sha256(Path(f.path).read_bytes()).hexdigest()[:16] for f in frames]
        req = {"task": task, "context": context, "frames": [{"path": f.path, "at_ms": f.at_ms} for f in frames],
               "answer_format": "[{at_ms, end_ms, label, judgment(count/not_count), confidence, reason}]"}
        out = self.store.get(_key("vision", task, digest, context), req)
        return [VisionFinding(int(x["at_ms"]), int(x["end_ms"]), str(x["label"]), x["judgment"], float(x["confidence"]), str(x.get("reason", "")))
                for x in out]
