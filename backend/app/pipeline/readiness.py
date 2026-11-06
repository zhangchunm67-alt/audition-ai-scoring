"""提交处理前的检查：评分配置与检测器协议是否对得上、产品讲解（S2）有没有可用的固定话术和校准记录。
检查不通过时直接拒绝提交，而不是让流水线跑失败后通知候选人重录。"""
from __future__ import annotations

import yaml
from sqlalchemy.orm import Session

from scoring import parse_config

from ..models.entities import AuditionSheet, ProductCard, RubricVersion
from .detectors import unsupported_items
from .detectors.sales import S2NotCalibrated, s2_material


def blockers(db: Session, sheet: AuditionSheet) -> list[str]:
    cfg = parse_config(yaml.safe_load(db.get(RubricVersion, sheet.rubric_version_id).yaml_text))
    out = [f"评分标准 {cfg.version} 与当前检测器不匹配：" + "、".join(bad)] if (bad := unsupported_items(cfg)) else []
    if any(it.id == "S2" for _, it in cfg.items()):
        try:
            s2_material(db.get(ProductCard, sheet.product_card_id).content)
        except S2NotCalibrated as exc:
            out.append(str(exc))
    return out


def s2_manifest(card: dict) -> dict[str, str]:
    """写进模型清单，报告追溯 S2 所用的固定话术和校准版本；校准记录未验证时报告标“非正式”。"""
    script, cal = card.get("fixed_script") or {}, card.get("s2_calibration") or {}
    if not cal:
        return {}
    return {"s2_fixed_script": str(script.get("version")), "s2_calibration": str(cal.get("version")),
            "s2_calibration_status": str(cal.get("status", "draft"))}
