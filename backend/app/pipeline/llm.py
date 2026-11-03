"""调用大模型：组装提示词、温度固定 0、按输出结构校验；格式不对重试一次。"""
from __future__ import annotations

from pydantic import ValidationError

from ..providers.base import LLM, ProviderError
from . import prompts

TEMPERATURE = 0.0  # C5：v1 所有大模型调用保持温度 0


def ask(llm: LLM, task: str, payload: dict, *, round_no: int = 1) -> dict:
    system, user, schema, model = prompts.build(task, payload)
    last: Exception | None = None
    for _ in range(2):
        raw = llm.complete_json(task, system, user, schema, temperature=TEMPERATURE, payload={**payload, "_round": round_no})
        try:
            return model.model_validate(raw).model_dump()
        except ValidationError as exc:
            last = exc
    raise ProviderError(f"大模型输出不符合 {task} 的结构：{last}")
