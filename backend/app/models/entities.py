"""数据模型。

约定：
- 候选人姓名、手机号等个人信息只存密文（*_enc）和用于查找的哈希；加密实现放在 services/crypto（里程碑 2）。
- 媒体文件只存在对象存储，这里只记位置、到期时间和删除时间。
- 评分标准、卖点卡、红线词表都按版本存，批次固定引用某个版本；报告记录所用版本和模型清单。
- 临界样本的每一轮是一条 pipeline_runs（round_no 1–3）；失败重试只增加 retry_count，不新增轮次。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, created_at, fk_uuid, uuid_pk

JSON = JSONB


def _enum(*values: str, name: str) -> Enum:
    return Enum(*values, name=name, native_enum=True, validate_strings=True)


ROLE = _enum("admin", "compliance", "calibrator", "hr", "anchor", name="user_role")
VERSION_STATUS = _enum("draft", "published", "retired", name="version_status")
LOCATION = _enum("studio", "home", name="recording_location")
HIRING = _enum("undecided", "hired", "not_hired", name="hiring_status")
LABEL = _enum("recommend", "pending", "not_recommend", name="verdict_label")


# ───────────────────────── 账号与审计 ─────────────────────────


class User(Base):
    """公司员工账号。候选人没有账号，只凭邀请链接。"""

    __tablename__ = "users"
    id: Mapped[uuid.UUID] = uuid_pk()
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(ROLE)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at()


class AuditLog(Base):
    """所有查看、导出、媒体访问、配置发布都写一条。只增不改。"""

    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = created_at()
    actor_type: Mapped[str] = mapped_column(_enum("user", "candidate", "system", name="actor_type"))
    actor_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)  # view_report / export_pdf / media_read / ...
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))


# ───────────────────────── 配置（M1） ─────────────────────────


class RubricVersion(Base):
    """计分配置版本。发布前须 scoring.publish_blockers() 为空。"""

    __tablename__ = "rubric_versions"
    id: Mapped[uuid.UUID] = uuid_pk()
    version: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(VERSION_STATUS, default="draft")
    yaml_text: Mapped[str] = mapped_column(Text)
    config_hash: Mapped[str] = mapped_column(String(80))
    created_by: Mapped[uuid.UUID | None] = fk_uuid("users.id", nullable=True)
    created_at: Mapped[datetime] = created_at()
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("(status = 'published') = (published_at IS NOT NULL) OR status = 'retired'", name="published_at"),)


class DetectorConfigVersion(Base):
    """检测配置版本（词表、抽帧率、提示词版本）。改了需要重跑模型。"""

    __tablename__ = "detector_config_versions"
    id: Mapped[uuid.UUID] = uuid_pk()
    version: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(VERSION_STATUS, default="draft")
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = created_at()


class Product(Base):
    __tablename__ = "products"
    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = created_at()


class ProductCard(Base):
    """卖点卡：必讲要点（分值、是否合规必讲）、针对性卖点、场景、术语白话、关键数字、禁用说法。"""

    __tablename__ = "product_cards"
    id: Mapped[uuid.UUID] = uuid_pk()
    product_id: Mapped[uuid.UUID] = fk_uuid("products.id")
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(VERSION_STATUS, default="draft")
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = created_at()
    __table_args__ = (UniqueConstraint("product_id", "version"),)


class Objection(Base):
    __tablename__ = "objections"
    id: Mapped[uuid.UUID] = uuid_pk()
    product_id: Mapped[uuid.UUID] = fk_uuid("products.id")
    text: Mapped[str] = mapped_column(Text)  # 弹幕原文
    answer_points: Mapped[list[Any]] = mapped_column(JSON, default=list)  # 正确答案要点（按条款）
    advantages: Mapped[list[Any]] = mapped_column(JSON, default=list)
    closing: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at()


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[uuid.UUID] = uuid_pk()
    product_id: Mapped[uuid.UUID] = fk_uuid("products.id")
    text: Mapped[str] = mapped_column(Text)
    full_points: Mapped[list[Any]] = mapped_column(JSON, default=list)
    partial_rule: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at()


class ReadingScript(Base):
    __tablename__ = "reading_scripts"
    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(String(128))
    text: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at()


class DrawRule(Base):
    """按产品配置抽题与计时（Q3 待确认：准备时间、异议弹出时间点）。"""

    __tablename__ = "draw_rules"
    id: Mapped[uuid.UUID] = uuid_pk()
    product_id: Mapped[uuid.UUID] = fk_uuid("products.id")
    objection_count: Mapped[int] = mapped_column(Integer, default=4)
    question_count: Mapped[int] = mapped_column(Integer, default=6)
    objection_times_ms: Mapped[list[int]] = mapped_column(JSON)  # 默认 [240000, 330000, 420000, 480000]
    prep_seconds: Mapped[int] = mapped_column(Integer, default=900)
    question_seconds: Mapped[int] = mapped_column(Integer, default=60)
    main_seconds: Mapped[int] = mapped_column(Integer, default=600)
    created_at: Mapped[datetime] = created_at()


class RedlineLexiconVersion(Base):
    """红线词表与正确说法，仅合规角色可编辑（权限在 API 层控制）。"""

    __tablename__ = "redline_lexicon_versions"
    id: Mapped[uuid.UUID] = uuid_pk()
    version: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(VERSION_STATUS, default="draft")
    content: Mapped[dict[str, Any]] = mapped_column(JSON)  # {R1: {keywords: [...], correct: [...]}, ...}
    created_by: Mapped[uuid.UUID | None] = fk_uuid("users.id", nullable=True)
    created_at: Mapped[datetime] = created_at()


# ───────────────────────── 批次与候选人 ─────────────────────────


class Batch(Base):
    __tablename__ = "batches"
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(128))
    product_id: Mapped[uuid.UUID] = fk_uuid("products.id")
    product_card_id: Mapped[uuid.UUID] = fk_uuid("product_cards.id")
    rubric_version_id: Mapped[uuid.UUID] = fk_uuid("rubric_versions.id")
    detector_config_version_id: Mapped[uuid.UUID] = fk_uuid("detector_config_versions.id")
    redline_lexicon_version_id: Mapped[uuid.UUID] = fk_uuid("redline_lexicon_versions.id")
    draw_rule_id: Mapped[uuid.UUID] = fk_uuid("draw_rules.id")
    audience: Mapped[str] = mapped_column(String(32))  # 达标线键；由谁设置待确认（B5）
    materials_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    created_by: Mapped[uuid.UUID | None] = fk_uuid("users.id", nullable=True)
    created_at: Mapped[datetime] = created_at()


class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[uuid.UUID] = uuid_pk()
    name_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    phone_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    phone_hash: Mapped[str | None] = mapped_column(String(80), index=True)
    hiring_status: Mapped[str] = mapped_column(HIRING, default="undecided")
    hiring_status_by: Mapped[uuid.UUID | None] = fk_uuid("users.id", nullable=True)
    linked_user_id: Mapped[uuid.UUID | None] = fk_uuid("users.id", nullable=True)  # 已录用新主播的账号（B16）
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[uuid.UUID] = uuid_pk()
    batch_id: Mapped[uuid.UUID] = fk_uuid("batches.id")
    candidate_id: Mapped[uuid.UUID] = fk_uuid("candidates.id")
    token_hash: Mapped[str] = mapped_column(String(80), unique=True)
    location: Mapped[str | None] = mapped_column(LOCATION)  # 由谁指定待确认（B6）
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts_used: Mapped[int] = mapped_column(Integer, default=0)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at()


class Consent(Base):
    __tablename__ = "consents"
    id: Mapped[uuid.UUID] = uuid_pk()
    invitation_id: Mapped[uuid.UUID] = fk_uuid("invitations.id")
    consent_text_version: Mapped[str] = mapped_column(String(64))
    granted: Mapped[bool] = mapped_column(Boolean)
    at: Mapped[datetime] = created_at()
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))


class Attempt(Base):
    """一次完整录制。重录是新的一条（attempt_no + 1）。"""

    __tablename__ = "attempts"
    id: Mapped[uuid.UUID] = uuid_pk()
    invitation_id: Mapped[uuid.UUID] = fk_uuid("invitations.id")
    attempt_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        _enum("created", "recording", "uploading", "submitted", "processing", "done", "failed", "interrupted", name="attempt_status"),
        default="created",
    )
    location: Mapped[str] = mapped_column(LOCATION)
    consent_id: Mapped[uuid.UUID | None] = fk_uuid("consents.id", nullable=True)
    drawn_objections: Mapped[list[Any]] = mapped_column(JSON, default=list)  # [{objection_id, popup_ms, shown_at_ms}]
    drawn_questions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    reading_script_id: Mapped[uuid.UUID | None] = fk_uuid("reading_scripts.id", nullable=True)
    events: Mapped[list[Any]] = mapped_column(JSON, default=list)  # 切屏、切后台、中断等
    main_duration_ms: Mapped[int | None] = mapped_column(Integer)
    retake_reason: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    __table_args__ = (UniqueConstraint("invitation_id", "attempt_no"),)


class MediaAsset(Base):
    """原视频、派生媒体（转码、音频、抽帧、证据片段）和上传分片。到期删除只删对象、留记录。"""

    __tablename__ = "media_assets"
    id: Mapped[uuid.UUID] = uuid_pk()
    attempt_id: Mapped[uuid.UUID] = fk_uuid("attempts.id")
    kind: Mapped[str] = mapped_column(
        _enum("raw_video", "normalized_video", "audio", "frame", "clip", "upload_part", name="media_kind")
    )
    segment: Mapped[str | None] = mapped_column(String(32))  # main / question:<id> / reading
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    encrypted: Mapped[bool] = mapped_column(Boolean, default=True)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class UploadSession(Base):
    """分片上传与断点续传。"""

    __tablename__ = "upload_sessions"
    id: Mapped[uuid.UUID] = uuid_pk()
    attempt_id: Mapped[uuid.UUID] = fk_uuid("attempts.id")
    segment: Mapped[str] = mapped_column(String(32))
    storage_key: Mapped[str] = mapped_column(String(512))
    multipart_upload_id: Mapped[str | None] = mapped_column(String(256))
    parts: Mapped[list[Any]] = mapped_column(JSON, default=list)  # [{part_no, etag, size}]
    status: Mapped[str] = mapped_column(_enum("open", "completed", "aborted", name="upload_status"), default="open")
    created_at: Mapped[datetime] = created_at()


# ───────────────────────── 处理（M3/M4） ─────────────────────────


class PipelineRun(Base):
    """一轮处理。round_no 1 为首轮，临界时追加 2、3。重试只加 retry_count。"""

    __tablename__ = "pipeline_runs"
    id: Mapped[uuid.UUID] = uuid_pk()
    attempt_id: Mapped[uuid.UUID] = fk_uuid("attempts.id")
    round_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        _enum("queued", "running", "completed", "failed", name="run_status"), default="queued"
    )
    stage: Mapped[str | None] = mapped_column(String(32))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    model_manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime] = created_at()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("attempt_id", "round_no"),
        CheckConstraint("round_no >= 1", name="round_no_positive"),
    )


class DetectorRun(Base):
    """每个检测器在某轮的结果状态；completed 的才进入 ScoringContext.completed_detectors。"""

    __tablename__ = "detector_runs"
    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = fk_uuid("pipeline_runs.id", ondelete="CASCADE")
    detector_id: Mapped[str] = mapped_column(String(32))  # 条目编号，或 "redlines"
    status: Mapped[str] = mapped_column(_enum("completed", "failed", name="detector_status"))
    tries: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime] = created_at()
    __table_args__ = (UniqueConstraint("run_id", "detector_id"),)


class Transcript(Base):
    __tablename__ = "transcripts"
    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = fk_uuid("pipeline_runs.id", ondelete="CASCADE")
    segment: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    words: Mapped[list[Any]] = mapped_column(JSON)  # [{w, start_ms, end_ms, conf}]
    provider: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(64))
    disfluency_removal: Mapped[bool] = mapped_column(Boolean, default=False)  # 必须为 false（关闭顺滑）
    created_at: Mapped[datetime] = created_at()
    __table_args__ = (UniqueConstraint("run_id", "segment"), CheckConstraint("NOT disfluency_removal", name="no_disfluency_removal"))


class AcousticFeatures(Base):
    __tablename__ = "acoustic_features"
    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = fk_uuid("pipeline_runs.id", ondelete="CASCADE")
    segment: Mapped[str] = mapped_column(String(32))
    features: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = created_at()


class EvidenceRow(Base):
    """证据，字段与 docs/rubric.md 第 9 节一致（加扩展字段 ref、value、segment）。"""

    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = fk_uuid("pipeline_runs.id", ondelete="CASCADE")
    evidence_id: Mapped[str] = mapped_column(String(64))
    item_id: Mapped[str] = mapped_column(String(8), index=True)
    kind: Mapped[str] = mapped_column(
        _enum("occurrence", "instance", "checklist_hit", "level", "question", "metric", "redline", name="evidence_kind")
    )
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)
    quote: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(String(128))
    judgment: Mapped[Any] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(_enum("rule", "llm", "audio", "vision", "human", name="evidence_source"))
    review: Mapped[dict[str, Any]] = mapped_column(JSON, default=lambda: {"status": "pending"})
    ref: Mapped[str | None] = mapped_column(String(128))
    value: Mapped[float | None] = mapped_column(Float)
    segment: Mapped[str | None] = mapped_column(String(32))
    __table_args__ = (
        UniqueConstraint("run_id", "evidence_id"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )


class ScoreResultRow(Base):
    """一轮的计分结果（scoring.RoundResult 原样存 JSON）。"""

    __tablename__ = "score_results"
    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = fk_uuid("pipeline_runs.id", ondelete="CASCADE")
    rubric_version_id: Mapped[uuid.UUID] = fk_uuid("rubric_versions.id")
    config_hash: Mapped[str] = mapped_column(String(80))
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = created_at()
    __table_args__ = (UniqueConstraint("run_id", "rubric_version_id"),)


# ───────────────────────── 报告（M5） ─────────────────────────


class Report(Base):
    """报告修订。按新版标准重算会产生新修订（政策待确认 B14），旧修订保留。"""

    __tablename__ = "reports"
    id: Mapped[uuid.UUID] = uuid_pk()
    attempt_id: Mapped[uuid.UUID] = fk_uuid("attempts.id")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    rubric_version_id: Mapped[uuid.UUID] = fk_uuid("rubric_versions.id")
    config_hash: Mapped[str] = mapped_column(String(80))
    detector_config_version_id: Mapped[uuid.UUID] = fk_uuid("detector_config_versions.id")
    model_manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    verdict: Mapped[dict[str, Any]] = mapped_column(JSON)  # scoring.FinalVerdict
    label: Mapped[str] = mapped_column(LABEL)
    conclusion: Mapped[str] = mapped_column(_enum("pass", "fail", name="verdict_conclusion"))
    critical: Mapped[bool] = mapped_column(Boolean)
    redline_hit: Mapped[bool] = mapped_column(Boolean)
    display_run_id: Mapped[uuid.UUID] = fk_uuid("pipeline_runs.id")
    created_at: Mapped[datetime] = created_at()
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("attempt_id", "revision"),)


class VideoAccessRequest(Base):
    """HR 申请查看原始视频（审批人待确认 B13）。"""

    __tablename__ = "video_access_requests"
    id: Mapped[uuid.UUID] = uuid_pk()
    requester_id: Mapped[uuid.UUID] = fk_uuid("users.id")
    attempt_id: Mapped[uuid.UUID] = fk_uuid("attempts.id")
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(_enum("pending", "approved", "denied", "expired", name="access_status"), default="pending")
    decided_by: Mapped[uuid.UUID | None] = fk_uuid("users.id", nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class Notification(Base):
    """通知发件箱：候选人通知和管理员告警。v1 全部走 Mock 渠道（C12）。"""

    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = uuid_pk()
    audience: Mapped[str] = mapped_column(_enum("candidate", "admin", name="notify_audience"))
    channel: Mapped[str] = mapped_column(String(32), default="mock")
    recipient_ref: Mapped[str] = mapped_column(String(128))
    template: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(_enum("queued", "sent", "failed", name="notify_status"), default="queued")
    created_at: Mapped[datetime] = created_at()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ───────────────────────── 校准（M6） ─────────────────────────


class GoldSet(Base):
    __tablename__ = "gold_sets"
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(128))
    purpose: Mapped[str] = mapped_column(_enum("prelaunch", "monthly_sample", "regression", name="gold_purpose"))
    created_at: Mapped[datetime] = created_at()
    samples: Mapped[list["GoldSample"]] = relationship(back_populates="gold_set")


class GoldSample(Base):
    __tablename__ = "gold_samples"
    id: Mapped[uuid.UUID] = uuid_pk()
    gold_set_id: Mapped[uuid.UUID] = fk_uuid("gold_sets.id")
    attempt_id: Mapped[uuid.UUID] = fk_uuid("attempts.id")
    gold_set: Mapped[GoldSet] = relationship(back_populates="samples")
    __table_args__ = (UniqueConstraint("gold_set_id", "attempt_id"),)


class CalibrationAssignment(Base):
    """背对背打分：每位校准员各自一条，提交前看不到别人的结果。"""

    __tablename__ = "calibration_assignments"
    id: Mapped[uuid.UUID] = uuid_pk()
    sample_id: Mapped[uuid.UUID] = fk_uuid("gold_samples.id")
    calibrator_id: Mapped[uuid.UUID] = fk_uuid("users.id")
    status: Mapped[str] = mapped_column(_enum("assigned", "submitted", name="assignment_status"), default="assigned")
    evidence: Mapped[list[Any]] = mapped_column(JSON, default=list)  # 证据级人工标注（source=human）
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    __table_args__ = (UniqueConstraint("sample_id", "calibrator_id"),)
