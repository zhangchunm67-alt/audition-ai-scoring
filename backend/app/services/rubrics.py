"""评分标准版本的公共逻辑。"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import case, select
from sqlalchemy.orm import Session

import yaml

from scoring import ConfigError, RubricConfig, config_hash, parse_config
from scoring.config import T3T4Item, T6Item

from ..models.entities import RubricVersion
from ..pipeline.detectors import unsupported_items
from . import audit

BUNDLED_RUBRIC_PATH = Path(__file__).resolve().parents[3] / "config/rubric/rubric-v0.3.yaml"


def sync_bundled(db: Session) -> RubricVersion:
    """补导入随代码交付的配置；保留现有版本的原文、哈希和发布状态，不导入演示业务数据。"""
    text = BUNDLED_RUBRIC_PATH.read_text("utf-8")
    cfg = parse_config(yaml.safe_load(text))
    if bad := unsupported_items(cfg):
        raise ValueError(f"随代码交付的评分配置与检测器不匹配：{'、'.join(bad)}")
    digest = config_hash(cfg)
    rv = db.scalar(select(RubricVersion).where(RubricVersion.version == cfg.version))
    if rv is not None:
        if rv.config_hash != digest or config_hash(load(rv)) != digest:
            raise ValueError(f"评分标准 {cfg.version} 已存在但内容不同；请使用新版本号，不能覆盖历史配置")
        return rv
    rv = RubricVersion(version=cfg.version, status="draft", yaml_text=text, config_hash=digest)
    db.add(rv)
    db.flush()
    audit.record(db, None, actor_type="system", actor_id=None, action="rubric_import", target_type="rubric_version",
                 target_id=str(rv.id), version=rv.version, config_hash=digest, source="bundled")
    return rv


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


def reference(db: Session, *, for_processing: bool = False) -> RubricVersion:
    """已发布优先，其次草稿；用于新评分时先排除与检测器不兼容的版本。"""
    versions = db.scalars(
        select(RubricVersion)
        .where(RubricVersion.status != "retired")
        .order_by(case((RubricVersion.status == "published", 0), else_=1), RubricVersion.created_at.desc())
    )
    for rv in versions:
        if not for_processing or not unsupported_items(load(rv)):
            return rv
    if for_processing:
        raise HTTPException(422, "没有与当前检测器兼容的评分标准，请联系管理员导入现行评分配置")
    raise HTTPException(422, "还没有导入任何评分标准版本")


def checklist_max(cfg: RubricConfig) -> int | None:
    """旧版 S2（卖点卡要点 + 结构）的要点满分；新版按固定话术打分，返回 None。"""
    return next((it.checklist_max for _, it in cfg.items() if isinstance(it, T3T4Item)), None)


def question_counts(cfg: RubricConfig) -> dict[str, int]:
    return {it.id: it.count for _, it in cfg.items() if isinstance(it, T6Item)}
