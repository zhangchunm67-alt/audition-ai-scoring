"""评分标准版本的公共逻辑。"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import case, select
from sqlalchemy.orm import Session

import yaml

from scoring import ConfigError, RubricConfig, parse_config
from scoring.config import T3T4Item, T6Item

from ..models.entities import RubricVersion


def parse_yaml(text: str) -> RubricConfig:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise HTTPException(422, f"YAML 格式错误：{exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(422, "YAML 顶层应为映射")
    try:
        return parse_config(data)
    except ConfigError as exc:
        raise HTTPException(422, f"评分配置不合法：{exc}") from exc


def load(rv: RubricVersion) -> RubricConfig:
    return parse_config(yaml.safe_load(rv.yaml_text))


def reference(db: Session) -> RubricVersion:
    """校验卖点卡、红线词表时参照的评分标准：最新的已发布版本；没有则最新草稿。"""
    rv = db.scalar(
        select(RubricVersion)
        .where(RubricVersion.status != "retired")
        .order_by(case((RubricVersion.status == "published", 0), else_=1), RubricVersion.created_at.desc())
        .limit(1)
    )
    if rv is None:
        raise HTTPException(422, "还没有导入任何评分标准版本")
    return rv


def checklist_max(cfg: RubricConfig) -> int | None:
    """旧版 S2（卖点卡要点 + 结构）的要点满分；新版按固定话术打分，返回 None。"""
    return next((it.checklist_max for _, it in cfg.items() if isinstance(it, T3T4Item)), None)


def question_counts(cfg: RubricConfig) -> dict[str, int]:
    return {it.id: it.count for _, it in cfg.items() if isinstance(it, T6Item)}
