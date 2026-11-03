"""大模型任务定义：提示词 + 输出结构。真实供应商用 system/user 文本；Mock 用 payload 做规则判断。

改提示词须升版本号（PROMPT_SET），并先在金标准集上跑回归（PRD 第 5 节“一致”）。
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

PROMPT_SET = "prompts-v1"


class _Judged(BaseModel):
    reason: str = ""
    confidence: float = Field(ge=0, le=1)


class IdJudgment(_Judged):
    id: str
    count: bool


class IdJudgments(BaseModel):
    items: list[IdJudgment]


class Level(_Judged):
    level: int
    quote: str = ""


class PointCheck(_Judged):
    id: str
    covered: bool
    correct: bool = True
    quote: str = ""


class ErrorClaim(_Judged):
    quote: str


class ProductCheck(BaseModel):
    points: list[PointCheck]
    structure_level: int
    structure_reason: str = ""
    structure_confidence: float = Field(ge=0, le=1)
    errors: list[ErrorClaim] = Field(default_factory=list)


class ObjectionCheck(_Judged):
    answered: bool
    direct_answer: bool = False
    advantage: bool = False
    altruistic_close: bool = False
    wrong: bool = False
    quote: str = ""


class Closing(_Judged):
    method: Literal["herd", "loss_aversion", "authority", "price_split", "sunk_cost", "other"]
    compliant: bool
    quote: str


class Closings(BaseModel):
    items: list[Closing]


class Opening(_Judged):
    what: bool
    who: bool
    hook: bool
    hook_invalid: bool = False
    level: int
    quote: str = ""


class Found(_Judged):
    quote: str
    valid: bool
    label: str = ""


class Founds(BaseModel):
    items: list[Found]


class Mainline(BaseModel):
    returned: list[bool]
    confidence: float = Field(ge=0, le=1)


class Answer(_Judged):
    level: Literal["full", "partial", "zero"]


class Rewrite(_Judged):
    suggestion: str


class RedlineJudgment(_Judged):
    id: str
    hit: bool


class RedlineJudgments(BaseModel):
    items: list[RedlineJudgment]


SYSTEM = (
    "你是保险直播主播试镜的评分助手。只根据给定的逐字稿和材料判断，不臆测。"
    "严格按要求的 JSON 结构输出，不输出其他内容。confidence 表示你对判断的把握（0–1）。"
)

TASKS: dict[str, tuple[str, type[BaseModel]]] = {
    "p2_filler": ("以下是主播讲解中召回的口头禅候选。判断每处“删掉或换成更短的说法后，意思是否不变”：不变则 count=true；"
                  "若该词承担实义（如真实数量“一个孩子”、条件“有医保的话”、推论“既然……那么”），count=false。", IdJudgments),
    "p10_laugh": ("以下是检测到笑声的片段及前后文。与内容无关的笑场、嘻笑、调侃产品或理赔记为 count=true；"
                  "自然微笑、讲轻松案例时的得体轻笑记为 count=false。", IdJudgments),
    "s1_need": ("评估“激发需求”：10=框架清楚（风险 → 现有保障缺口 → 解决办法），有事实或场景支撑并自然引到产品；"
                "6=讲了必要性但框架不完整或缺支撑；3=一句带过；0=没有。夸大风险、制造焦虑不得分。", Level),
    "s2_product": ("对照卖点卡必讲要点逐项核对：讲到且讲对 covered=true、correct=true；讲到但与条款不符 correct=false。"
                   "另给结构等级：20=有明确框架且过渡清楚；14=基本有序偶有跳跃；7=零散来回重复；0=混乱。"
                   "列出所有与条款不符的说法（errors）。", ProductCheck),
    "s3_objection": ("判断主播对这条观众异议的回答（按回答内容归属，不按时间窗口）：是否正面回答（且与条款一致）、"
                     "是否引回产品优势、是否站在观众角度利他收尾、是否答错。没有回应则 answered=false。", ObjectionCheck),
    "s4_closing": ("找出所有促成投保决定的语句并归类（从众、损失规避、权威认同、价格拆分、沉没成本）。"
                   "编造数字、制造焦虑、停售涨价施压、虚构背书、算错价格的记 compliant=false。", Closings),
    "l1_opening": ("这是主体段开头 30 秒。判断是否讲到：讲什么（what）、对谁有用（who）、为什么现在听（hook）。"
                   "20=三件都有且钩子具体；14=有两件；8=只有寒暄加简单介绍；0=没进主题。钩子不实或诱导 hook_invalid=true。", Opening),
    "l2_structure": ("找出所有“总分 / 总分总 / 结论先行”的段落：先给结论或总述，分点展开且在总述范围内，"
                     "总分总要回到结论，至少 3 句。只有“第一”没有“第二”、总述与分点对不上的 valid=false。", Founds),
    "l3_deduction": ("找出所有推论句（所以、因此、一定、必须等），判断前提是否成立、能否推出结论。"
                     "前提不成立、以偏概全或推不出结论的 valid=false（演绎错误）。", Founds),
    "l4_induction": ("找出所有把卖点或理由归纳成要点的组：3–4 个并列要点、互不重叠、覆盖主要内容的 valid=true；"
                     "只有 2 点、5 点以上或要点重叠的 valid=false。", Founds),
    "l5_facts": ("找出所有具体事实和数字陈述，对照卖点卡关键数字核对：具体、可核验、与条款一致的 valid=true；"
                 "与条款不符或无法核验的统计 valid=false。label 填事实名称。", Founds),
    "o1_terms": ("对照术语表，找出讲到术语时紧跟白话解释且解释准确的地方，label 填术语；只说术语不解释或解释错误的 valid=false。", Founds),
    "o2_targeted": ("对照针对性卖点，找出针对目标人群具体痛点讲出本产品具体解决点的地方，label 填卖点；泛泛而谈的 valid=false。", Founds),
    "o3_scene": ("找出描绘具体使用场景的地方（有具体的人、地点或动作）；抽象说法 valid=false。", Founds),
    "o4_mainline": ("对每条异议，判断主播回答完后是否自然回到讲品主线（returned，按异议顺序）。", Mainline),
    "o5_answer": ("对照满分要点判断这道知识题的回答：full=答到全部要点；partial=方向对但漏了要点或表述不准；zero=答错或没答。", Answer),
    "rewrite": ("这是主播试镜中有问题的一句话，以及评分时发现的问题。请给出一句示范说法：保留原意，改掉指出的问题"
                "（去掉口头禅、讲准条款、补上白话解释、去掉施压或夸大等），不编造产品信息，不超过原句长度的 1.5 倍。", Rewrite),
    "redline_judge": ("以下是按合规红线词表召回的候选句。结合上下文判断是否真的触犯对应红线（hit）。"
                      "如实讲条款、否定或纠正错误说法的不算。", RedlineJudgments),
}


def build(task: str, payload: dict) -> tuple[str, str, dict, type[BaseModel]]:
    instruction, model = TASKS[task]
    user = f"{instruction}\n\n输入：\n{json.dumps(payload, ensure_ascii=False, indent=1)}\n\n按以下 JSON Schema 输出：\n" + json.dumps(
        model.model_json_schema(), ensure_ascii=False)
    return SYSTEM, user, model.model_json_schema(), model


def prompt_set_hash() -> str:
    blob = json.dumps({k: v[0] for k, v in TASKS.items()} | {"_system": SYSTEM}, ensure_ascii=False, sort_keys=True)
    return f"{PROMPT_SET}:{hashlib.sha256(blob.encode()).hexdigest()[:12]}"
