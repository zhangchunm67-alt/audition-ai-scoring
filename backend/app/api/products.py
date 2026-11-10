"""产品、卖点卡、异议库、知识题库、抽题规则（M1-2、M1-3）。"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Literal
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.entities import DrawRule, Objection, Product, ProductCard, Question, User
from ..security.rbac import Perm
from ..services import audit
from ..services.rubrics import checklist_max, load, reference
from .deps import DB, require

router = APIRouter(tags=["产品与题库"])
Read = Depends(require(Perm.config_read))
Write = Depends(require(Perm.config_write))


def _log(db, request, actor: User, action: str, ttype: str, tid, **kw) -> None:
    audit.record(db, request, actor_type="user", actor_id=str(actor.id), action=action, target_type=ttype, target_id=str(tid), **kw)


# ───────────── 产品 ─────────────


class ProductIn(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{2,64}$")
    name: str = Field(min_length=1, max_length=128)


class ProductOut(ProductIn):
    id: uuid.UUID
    published_card_version: int | None = None
    active_objections: int = 0
    active_questions: int = 0


def _product_out(db: Session, p: Product) -> ProductOut:
    card = db.scalar(select(ProductCard.version).where(ProductCard.product_id == p.id, ProductCard.status == "published"))
    n_obj = db.scalar(select(func.count()).select_from(Objection).where(Objection.product_id == p.id, Objection.active))
    n_q = db.scalar(select(func.count()).select_from(Question).where(Question.product_id == p.id, Question.active))
    return ProductOut(id=p.id, code=p.code, name=p.name, published_card_version=card, active_objections=n_obj, active_questions=n_q)


def _product(db: Session, pid: uuid.UUID) -> Product:
    p = db.get(Product, pid)
    if p is None:
        raise HTTPException(404, "产品不存在")
    return p


@router.get("/products", response_model=list[ProductOut])
def list_products(db: Session = DB, _: User = Read) -> list[ProductOut]:
    return [_product_out(db, p) for p in db.scalars(select(Product).order_by(Product.created_at))]


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(body: ProductIn, request: Request, db: Session = DB, actor: User = Write) -> ProductOut:
    if db.scalar(select(Product).where(Product.code == body.code)):
        raise HTTPException(409, "产品编码已存在")
    p = Product(code=body.code, name=body.name)
    db.add(p)
    db.flush()
    _log(db, request, actor, "product_create", "product", p.id)
    db.commit()
    return _product_out(db, p)


@router.get("/products/{pid}", response_model=ProductOut)
def get_product(pid: uuid.UUID, db: Session = DB, _: User = Read) -> ProductOut:
    return _product_out(db, _product(db, pid))


# ───────────── 卖点卡（按版本） ─────────────


class CardPoint(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    name: str = Field(min_length=1)
    points: int = Field(ge=0)
    compliance_required: bool = False


class GlossaryEntry(BaseModel):
    term: str = Field(min_length=1)
    plain: str = Field(min_length=1)  # 白话解释


class KeyNumber(BaseModel):
    name: str = Field(min_length=1)
    value: str = Field(min_length=1)


class FixedScript(BaseModel):
    """S2 固定话术（评分表：根据固定话术的完成准确程度打分）。改话术须换版本号，旧的校准记录随之失效。"""

    version: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    text: str = Field(min_length=1)


class CalibrationAnchor(BaseModel):
    """校准样例：人工标注的一段讲解及其 S2 分，供模型对齐给分尺度。"""

    score: int = Field(ge=0, le=50)
    excerpt: str = Field(min_length=1)
    note: str | None = None


S2_MIN_TRAIN_SAMPLES = 20  # 交接口径：每个产品 20–30 份人工标注样本
S2_MIN_HOLDOUT = 10  # 留出验证样本下限：太少的一致率没有意义
S2_MIN_AGREEMENT = 0.85  # 留出样本上 AI 与人工一致的比例下限，与条目级监控线 TARGET_ITEM 相同


class S2Calibration(BaseModel):
    """某产品、某版固定话术的 S2 校准记录（CAL-S2-PRODUCT）。原始人工标注另行保存，这里只记结论和样例。
    status=draft：可用于试跑，报告标“非正式”；validated：须有训练样本和留出验证样本的一致性结果。"""

    version: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    fixed_script_version: str
    status: Literal["draft", "validated"] = "draft"
    train_samples: int = Field(default=0, ge=0)
    holdout_samples: int = Field(default=0, ge=0)
    holdout_agreement: float | None = Field(default=None, ge=0, le=1)  # 留出样本上 AI 与人工 S2 一致的比例
    anchors: list[CalibrationAnchor] = Field(default_factory=list)
    note: str | None = None

    @model_validator(mode="after")
    def _validated(self) -> "S2Calibration":
        if self.status == "validated":
            if self.train_samples < S2_MIN_TRAIN_SAMPLES:
                raise ValueError(f"校准样本至少 {S2_MIN_TRAIN_SAMPLES} 份才能标为已验证")
            if self.holdout_samples < S2_MIN_HOLDOUT or self.holdout_agreement is None:
                raise ValueError(f"标为已验证须有至少 {S2_MIN_HOLDOUT} 份留出验证样本及一致率")
            if self.holdout_agreement < S2_MIN_AGREEMENT:
                raise ValueError(f"留出样本一致率 {self.holdout_agreement:.0%} 低于 {S2_MIN_AGREEMENT:.0%}，不能标为已验证")
        return self


class CardContent(BaseModel):
    checklist: list[CardPoint] = Field(default_factory=list)  # 必讲要点：仅旧版 rubric-v0.1 的 S2 用，新版只作讲解提示
    fixed_script: FixedScript | None = None  # S2 固定话术
    s2_calibration: S2Calibration | None = None  # S2 校准记录
    targeted_points: list[str] = Field(default_factory=list)  # 针对性卖点
    scenarios: list[str] = Field(default_factory=list)  # 使用场景
    glossary: list[GlossaryEntry] = Field(default_factory=list)  # 术语白话对照
    key_numbers: list[KeyNumber] = Field(default_factory=list)  # 关键数字
    banned_phrases: list[str] = Field(default_factory=list)  # 禁用说法

    @field_validator("checklist")
    @classmethod
    def _unique(cls, v: list[CardPoint]) -> list[CardPoint]:
        ids = [p.id for p in v]
        if len(set(ids)) != len(ids):
            raise ValueError("要点编号重复")
        return v

    @model_validator(mode="after")
    def _calibration_matches_script(self) -> "CardContent":
        if self.s2_calibration is not None:
            if self.fixed_script is None:
                raise ValueError("没有固定话术，不能登记 S2 校准记录")
            if self.s2_calibration.fixed_script_version != self.fixed_script.version:
                raise ValueError("S2 校准记录对应的固定话术版本与本卡固定话术版本不一致")
        return self


class CardOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    version: int
    status: str
    content: CardContent
    points_total: int
    created_at: datetime


def check_card_total(content: dict | CardContent, required: int | None) -> None:
    """C25（只适用于旧版带卖点卡要点分的评分标准）：必讲要点分值合计必须等于 S2 的要点满分。新版 S2 按固定话术打分，required 为 None。"""
    if required is None:
        return
    pts = content.checklist if isinstance(content, CardContent) else [CardPoint(**p) for p in content.get("checklist", [])]
    total = sum(p.points for p in pts)
    if total != required:
        raise HTTPException(422, f"必讲要点分值合计为 {total}，必须等于产品讲解的要点满分 {required}")


def _card_out(c: ProductCard) -> CardOut:
    content = CardContent(**c.content)
    return CardOut(id=c.id, product_id=c.product_id, version=c.version, status=c.status, content=content,
                   points_total=sum(p.points for p in content.checklist), created_at=c.created_at)


@router.get("/products/{pid}/cards", response_model=list[CardOut])
def list_cards(pid: uuid.UUID, db: Session = DB, _: User = Read) -> list[CardOut]:
    _product(db, pid)
    return [_card_out(c) for c in db.scalars(select(ProductCard).where(ProductCard.product_id == pid).order_by(ProductCard.version.desc()))]


@router.post("/products/{pid}/cards", response_model=CardOut, status_code=201)
def create_card(pid: uuid.UUID, body: CardContent, request: Request, db: Session = DB, actor: User = Write) -> CardOut:
    _product(db, pid)
    check_card_total(body, checklist_max(load(reference(db))))
    last = db.scalar(select(func.max(ProductCard.version)).where(ProductCard.product_id == pid)) or 0
    c = ProductCard(product_id=pid, version=last + 1, status="draft", content=body.model_dump(mode="json"))
    db.add(c)
    db.flush()
    _log(db, request, actor, "card_create", "product_card", c.id, version=c.version)
    db.commit()
    return _card_out(c)


@router.post("/cards/{cid}/publish", response_model=CardOut)
def publish_card(cid: uuid.UUID, request: Request, db: Session = DB, actor: User = Write) -> CardOut:
    c = db.get(ProductCard, cid)
    if c is None:
        raise HTTPException(404, "卖点卡不存在")
    if c.status != "draft":
        raise HTTPException(409, "只有草稿可以发布")
    check_card_total(c.content, checklist_max(load(reference(db))))
    for old in db.scalars(select(ProductCard).where(ProductCard.product_id == c.product_id, ProductCard.status == "published")):
        old.status = "retired"
    c.status = "published"
    _log(db, request, actor, "card_publish", "product_card", c.id, version=c.version)
    db.commit()
    return _card_out(c)


@router.put("/cards/{cid}/s2-calibration", response_model=CardOut)
def put_s2_calibration(cid: uuid.UUID, body: S2Calibration, request: Request, db: Session = DB, actor: User = Write) -> CardOut:
    """登记或更新 S2 校准记录。固定话术不变时，校准可以在卖点卡发布之后补登（已生成的题单也能用上），每次修改写审计。"""
    c = db.get(ProductCard, cid)
    if c is None:
        raise HTTPException(404, "卖点卡不存在")
    if c.status == "retired":
        raise HTTPException(409, "已停用的卖点卡不能再登记校准")
    try:
        content = CardContent(**{**c.content, "s2_calibration": body.model_dump(mode="json")})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    old = (c.content or {}).get("s2_calibration")
    c.content = content.model_dump(mode="json")
    _log(db, request, actor, "card_s2_calibration", "product_card", c.id, version=c.version, calibration=body.version,
         status=body.status, previous=(old or {}).get("version"))
    db.commit()
    return _card_out(c)


# ───────────── 异议库、知识题库 ─────────────


class ObjectionIn(BaseModel):
    text: str = Field(min_length=1)  # 弹幕原文
    answer_points: list[str] = Field(default_factory=list)  # 正确答案要点（按条款）
    advantages: list[str] = Field(default_factory=list)  # 可强调的优势
    closing: str | None = None  # 合适的收尾
    active: bool = True


class ObjectionOut(ObjectionIn):
    id: uuid.UUID
    product_id: uuid.UUID


class QuestionIn(BaseModel):
    text: str = Field(min_length=1)
    full_points: list[str] = Field(min_length=1)  # 满分要点
    partial_rule: str | None = None  # 部分分条件
    active: bool = True


class QuestionOut(QuestionIn):
    id: uuid.UUID
    product_id: uuid.UUID


def _crud(kind: str, model, In, Out, label: str):
    def out(o):
        return Out(id=o.id, product_id=o.product_id, **{k: getattr(o, k) for k in In.model_fields})

    @router.get(f"/products/{{pid}}/{kind}", response_model=list[Out], name=f"list_{kind}")
    def list_(pid: uuid.UUID, include_inactive: bool = False, db: Session = DB, _: User = Read):
        _product(db, pid)
        q = select(model).where(model.product_id == pid)
        if not include_inactive:
            q = q.where(model.active)
        return [out(o) for o in db.scalars(q.order_by(model.created_at))]

    @router.post(f"/products/{{pid}}/{kind}", response_model=Out, status_code=201, name=f"create_{kind}")
    def create(pid: uuid.UUID, body: In, request: Request, db: Session = DB, actor: User = Write):  # type: ignore[valid-type]
        _product(db, pid)
        o = model(product_id=pid, **body.model_dump())
        db.add(o)
        db.flush()
        _log(db, request, actor, f"{label}_create", label, o.id)
        db.commit()
        return out(o)

    @router.put(f"/{kind}/{{oid}}", response_model=Out, name=f"update_{kind}")
    def update(oid: uuid.UUID, body: In, request: Request, db: Session = DB, actor: User = Write):  # type: ignore[valid-type]
        o = db.get(model, oid)
        if o is None:
            raise HTTPException(404, "记录不存在")
        for k, v in body.model_dump().items():
            setattr(o, k, v)
        _log(db, request, actor, f"{label}_update", label, o.id)
        db.commit()
        return out(o)


_crud("objections", Objection, ObjectionIn, ObjectionOut, "objection")
_crud("questions", Question, QuestionIn, QuestionOut, "question")


# ───────────── 抽题规则 ─────────────


class DrawRuleIn(BaseModel):
    objection_count: int = Field(default=4, ge=1)
    question_count: int = Field(default=0, ge=0)  # 知识题：评分表 20261105 已删除 O5，新版评分标准为 0
    objection_times_ms: list[int] = Field(default_factory=lambda: [240_000, 330_000, 420_000, 480_000])  # Q3 默认
    prep_seconds: int = Field(default=900, ge=0)
    question_seconds: int = Field(default=60, ge=1)
    main_seconds: int = Field(default=600, ge=60)

    @model_validator(mode="after")
    def _check(self) -> "DrawRuleIn":
        t = self.objection_times_ms
        if len(t) != self.objection_count:
            raise ValueError("异议弹出时间点的个数须等于异议条数")
        if t != sorted(set(t)):
            raise ValueError("异议弹出时间点须严格递增")
        if t and (t[0] <= 0 or t[-1] >= self.main_seconds * 1000):
            raise ValueError("异议弹出时间点须落在主体段内")
        return self


class DrawRuleOut(DrawRuleIn):
    id: uuid.UUID
    product_id: uuid.UUID


def _rule_out(r: DrawRule) -> DrawRuleOut:
    return DrawRuleOut(id=r.id, product_id=r.product_id, **{k: getattr(r, k) for k in DrawRuleIn.model_fields})


@router.get("/products/{pid}/draw-rule", response_model=DrawRuleOut | None)
def get_rule(pid: uuid.UUID, db: Session = DB, _: User = Read):
    _product(db, pid)
    r = db.scalar(select(DrawRule).where(DrawRule.product_id == pid).order_by(DrawRule.created_at.desc()).limit(1))
    return _rule_out(r) if r else None


@router.put("/products/{pid}/draw-rule", response_model=DrawRuleOut)
def put_rule(pid: uuid.UUID, body: DrawRuleIn, request: Request, db: Session = DB, actor: User = Write) -> DrawRuleOut:
    """每次修改都新增一条，旧规则保留；已生成的题单存有规则快照。"""
    _product(db, pid)
    r = DrawRule(product_id=pid, **body.model_dump())
    db.add(r)
    db.flush()
    _log(db, request, actor, "draw_rule_update", "draw_rule", r.id, **body.model_dump())
    db.commit()
    return _rule_out(r)
