"""提交处理前的检查：评分配置与检测器协议是否对得上、产品讲解（S2）有没有可用的固定话术和校准记录。
检查不通过时直接拒绝提交，而不是让流水线跑失败后通知候选人重录。"""
from __future__ import annotations

import yaml
from sqlalchemy.orm import Session

from scoring import parse_config

from ..models.entities import AuditionSheet, ProductCard, RubricVersion
from .detectors import unavailable_capabilities, unsupported_items
from .detectors.sales import S2NotCalibrated, s2_material
from ..providers.registry import allow_mock_scoring, mock_capabilities


def blockers(db: Session, sheet: AuditionSheet, providers=None, *, live: bool = False) -> list[str]:
    """providers 给出时同时检查模型：语音识别是所有条目的前提，没有配置就不能处理；
    其他能力没有配置时依赖它的条目转评委打分，不拦提交。
    live（录播评估，C37）：直播讲的产品不一定有固定话术和校准记录，缺的时候 S2 转评委打分，不拦提交。"""
    cfg = parse_config(yaml.safe_load(db.get(RubricVersion, sheet.rubric_version_id).yaml_text))
    out = [f"评分标准 {cfg.version} 与当前检测器不匹配：" + "、".join(bad)] if (bad := unsupported_items(cfg)) else []
    if providers is not None and "asr" in unavailable_capabilities(providers):
        out.append("语音识别模型没有配置（APP_ASR），录像无法处理；生产环境不能使用 Mock")
    if providers is not None and not allow_mock_scoring() and "asr" in mock_capabilities(providers):
        out.append("当前为 Mock 模拟语音识别，不能评估真实录像；请先接入真实语音识别。演示测试须在隔离环境显式启用 APP_ALLOW_MOCK_SCORING")
    if not live and any(it.id == "S2" for _, it in cfg.items()):
        try:
            s2_material(db.get(ProductCard, sheet.product_card_id).content)
        except S2NotCalibrated as exc:
            out.append(str(exc))
    return out


def material_review_items(card: dict) -> set[str]:
    """无法依据现有资料核验的项目留待人工，不按空结果记零。"""
    manual = set()
    if not card.get("key_numbers"):
        manual.add("L5")
    if not card.get("targeted_points") and not str((card.get("fixed_script") or {}).get("text") or "").strip():
        manual.add("O2")
    return manual


def s2_ready(card: dict) -> bool:
    try:
        s2_material(card)
    except S2NotCalibrated:
        return False
    return True


def s2_manifest(card: dict) -> dict[str, str]:
    """写进模型清单，报告追溯 S2 所用的固定话术和校准版本；校准记录未验证时报告标“非正式”。"""
    script, cal = card.get("fixed_script") or {}, card.get("s2_calibration") or {}
    if not cal:
        return {}
    return {"s2_fixed_script": str(script.get("version")), "s2_calibration": str(cal.get("version")),
            "s2_calibration_status": str(cal.get("status", "draft"))}
