"""录像：登记 → 分片上传（断点续传）→ 标分段和异议时间 → 提交处理（C26–C30）。
两种模式：audition（按题单录的试镜）和 live（直播录播，没有题单，整段视频评分，C37）。"""
from __future__ import annotations

import hashlib
import math
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.entities import AuditionSheet, ConsentRecord, MediaAsset, PipelineRun, Product, Recording, Report, RubricVersion, UploadSession, User
from ..pipeline import orchestrator, readiness
from ..providers.registry import get_providers
from ..security.rbac import Perm
from ..services import audit
from ..services import human_review as human
from ..services.media import ProbeError, probe
from ..services.rubrics import load, reference
from ..services.storage import Part, get_storage
from ..settings import get_settings
from .candidates import get_candidate, name_of
from .deps import DB, require
from .sheets import create_live_sheet

router = APIRouter(tags=["录像"])
Read = Depends(require(Perm.report_read_all))
Write = Depends(require(Perm.recording_upload))
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
MAX_LIVE_OBJECTIONS = 50


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _log(db, request, actor: User, action: str, ttype: str, tid, **kw) -> None:
    audit.record(db, request, actor_type="user", actor_id=str(actor.id), action=action, target_type=ttype, target_id=str(tid), **kw)


# ───────────── 输出结构 ─────────────


class FileIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(pattern=r"^video/[\w.+-]+$")
    size_bytes: int = Field(gt=0)


class RecordingIn(FileIn):
    candidate_id: uuid.UUID
    mode: Literal["audition", "live"] = "audition"
    sheet_id: uuid.UUID | None = None  # 试镜必填
    product_id: uuid.UUID | None = None  # 录播必填：没有题单，直接选产品（C37）
    rubric_version_id: uuid.UUID | None = None  # 录播可选：不给时用现行评分标准（最新已发布，没有则最新草稿）
    consent_record_id: uuid.UUID
    audience: str  # 必选，不设默认值（C27）
    props_available: bool  # 必填：画面里有无贴片 / KT 板（C26）

    @model_validator(mode="after")
    def _by_mode(self) -> "RecordingIn":
        if self.mode == "audition" and self.sheet_id is None:
            raise ValueError("试镜录像须选择题单")
        if self.mode == "live" and (self.product_id is None or self.sheet_id is not None):
            raise ValueError("录播没有题单，须选择产品")
        return self


class UploadOut(BaseModel):
    id: uuid.UUID
    status: str
    part_size: int
    total_size: int
    part_count: int
    received_parts: list[int]
    received_bytes: int


class SegmentsIn(BaseModel):
    """时间都以毫秒计。知识题起点按题单顺序；异议时间相对主体段起点。"""

    main_start_ms: int = Field(ge=0)
    question_starts_ms: list[int]
    reading_start_ms: int
    objection_offsets_ms: list[int]


class LiveObjectionIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    video_ms: int = Field(ge=0)


class RangeIn(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)


class LiveMarksIn(BaseModel):
    """录播标注（C37）。时间都是整段视频的毫秒。
    objections：主播回应过的真实观众问题（出现时间和原文），可以为空；exclusions：不是主播本人在讲的时段（副播插话等）。"""

    objections: list[LiveObjectionIn] = Field(max_length=MAX_LIVE_OBJECTIONS)
    exclusions: list[RangeIn] = Field(default_factory=list, max_length=200)


class RecordingOut(BaseModel):
    id: uuid.UUID
    status: str
    mode: str
    candidate_id: uuid.UUID
    candidate_name: str
    sheet_id: uuid.UUID
    sheet_code: str
    product_name: str
    uses_draft_config: bool
    audience: str
    props_available: bool
    sheet_objections: list[dict]
    sheet_questions: list[dict]
    main_seconds: int
    video_asset_id: uuid.UUID | None
    video_duration_ms: int | None
    main_duration_ms: int | None
    segments: list[dict]
    objection_times: list[dict]
    exclusions: list[dict]
    upload: UploadOut | None
    warnings: list[str]
    created_at: datetime
    submitted_at: datetime | None
    processing_started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_reason: str | None = None
    report_id: uuid.UUID | None = None


def _upload_out(u: UploadSession) -> UploadOut:
    return UploadOut(id=u.id, status=u.status, part_size=u.part_size, total_size=u.total_size,
                     part_count=math.ceil(u.total_size / u.part_size), received_parts=sorted(p["part_no"] for p in u.parts),
                     received_bytes=sum(p["size"] for p in u.parts))


def _video(db: Session, rec: Recording) -> MediaAsset | None:
    return db.scalar(select(MediaAsset).where(MediaAsset.recording_id == rec.id, MediaAsset.kind == "raw_video", MediaAsset.deleted_at.is_(None)))


def _warnings(rec: Recording, sheet: AuditionSheet) -> list[str]:
    """不再提示“主体段不是 10 分钟”：评分不截取 10 分钟，P2 按每 10 分钟的次数换算（C36）。"""
    w = []
    if rec.mode == "live" and rec.segments and not rec.objection_times:
        w.append("没有标出观众异议：解答异议（S3）不适用，销售循环按其余条目折算；节奏与气氛（O4）由评委打分")
    return w


def _out(db: Session, rec: Recording) -> RecordingOut:
    sheet = db.get(AuditionSheet, rec.sheet_id)
    up = db.scalar(select(UploadSession).where(UploadSession.recording_id == rec.id).order_by(UploadSession.created_at.desc()).limit(1))
    v = _video(db, rec)
    return RecordingOut(
        id=rec.id, status=rec.status, mode=rec.mode, candidate_id=rec.candidate_id, candidate_name=name_of(get_candidate(db, rec.candidate_id)),
        sheet_id=sheet.id, sheet_code=sheet.code, product_name=db.get(Product, sheet.product_id).name,
        uses_draft_config=sheet.uses_draft_config, audience=rec.audience, props_available=rec.props_available,
        sheet_objections=sheet.objections, sheet_questions=sheet.questions, main_seconds=sheet.draw_rule_snapshot.get("main_seconds", 600),
        video_asset_id=v.id if v else None, video_duration_ms=rec.video_duration_ms, main_duration_ms=rec.main_duration_ms,
        segments=rec.segments, objection_times=rec.objection_times, exclusions=rec.exclusions or [], upload=_upload_out(up) if up else None,
        warnings=_warnings(rec, sheet), created_at=rec.created_at, submitted_at=rec.submitted_at,
        processing_started_at=rec.processing_started_at, finished_at=rec.finished_at, failure_reason=rec.failure_reason,
        report_id=db.scalar(select(Report.id).where(Report.recording_id == rec.id, Report.superseded_at.is_(None))),
    )


def _get(db: Session, rid: uuid.UUID) -> Recording:
    rec = db.get(Recording, rid)
    if rec is None:
        raise HTTPException(404, "录像记录不存在")
    return rec


def _check_file(f: FileIn) -> str:
    ext = PurePosixPath(f.filename).suffix.lower()
    if ext not in VIDEO_EXT:
        raise HTTPException(422, f"只支持 {'、'.join(sorted(VIDEO_EXT))} 格式的视频")
    if f.size_bytes > get_settings().max_upload_bytes:
        raise HTTPException(422, f"文件超过上限 {get_settings().max_upload_bytes // 1024**3} GB")
    return ext


def _open_upload(db: Session, rec: Recording, f: FileIn, ext: str, actor: User) -> UploadSession:
    key = f"recordings/{rec.id}/raw/{uuid.uuid4().hex}{ext}"
    u = UploadSession(
        recording_id=rec.id, segment="full", storage_key=key, multipart_upload_id=get_storage().start_multipart(key, f.content_type),
        part_size=get_settings().upload_part_bytes, total_size=f.size_bytes, filename=f.filename, content_type=f.content_type,
        created_by=actor.id, parts=[],
    )
    db.add(u)
    db.flush()
    return u


def _abort_open(db: Session, rec: Recording) -> None:
    for u in db.scalars(select(UploadSession).where(UploadSession.recording_id == rec.id, UploadSession.status == "open")):
        get_storage().abort_multipart(u.storage_key, u.multipart_upload_id)
        u.status = "aborted"


def _drop_video(db: Session, rec: Recording) -> None:
    v = _video(db, rec)
    if v:
        get_storage().delete(v.storage_key)
        v.deleted_at = _now()


# ───────────── 录像 ─────────────


@router.get("/recordings", response_model=list[RecordingOut])
def list_recordings(status: str | None = None, db: Session = DB, _: User = Read) -> list[RecordingOut]:
    q = select(Recording).order_by(Recording.created_at.desc())
    if status:
        q = q.where(Recording.status == status)
    return [_out(db, r) for r in db.scalars(q.limit(500))]


@router.post("/recordings", response_model=RecordingOut, status_code=201)
def create_recording(body: RecordingIn, request: Request, db: Session = DB, actor: User = Write) -> RecordingOut:
    cand = get_candidate(db, body.candidate_id)
    consent = db.get(ConsentRecord, body.consent_record_id)
    if consent is None or consent.candidate_id != cand.id:
        raise HTTPException(422, "请先为该候选人登记书面同意，未登记不能上传（C30）")
    ext = _check_file(body)
    if body.mode == "live":
        sheet = create_live_sheet(db, body.product_id, body.rubric_version_id or reference(db, for_processing=True).id, actor)
    else:
        sheet = db.get(AuditionSheet, body.sheet_id)
        if sheet is None or sheet.kind != "audition":
            raise HTTPException(404, "题单不存在")
        if sheet.status != "issued":
            raise HTTPException(409, "题单已使用或已作废")
    thresholds = load(db.get(RubricVersion, sheet.rubric_version_id)).thresholds
    if body.audience not in thresholds:
        raise HTTPException(422, f"适用达标线必须是 {'、'.join(thresholds)} 之一")
    rec = Recording(mode=body.mode, candidate_id=cand.id, sheet_id=sheet.id, consent_record_id=consent.id, audience=body.audience,
                    props_available=body.props_available, uploaded_by=actor.id, status="uploading")
    db.add(rec)
    db.flush()
    sheet.status = "used"
    u = _open_upload(db, rec, body, ext, actor)
    _log(db, request, actor, "recording_create", "recording", rec.id, mode=rec.mode, sheet=sheet.code, audience=rec.audience,
         props_available=rec.props_available, upload_id=str(u.id))
    db.commit()
    return _out(db, rec)


@router.get("/recordings/{rid}", response_model=RecordingOut)
def get_recording(rid: uuid.UUID, request: Request, db: Session = DB, viewer: User = Read) -> RecordingOut:
    rec = _get(db, rid)
    out = _out(db, rec)
    _log(db, request, viewer, "recording_view", "recording", rid)
    db.commit()
    return out


@router.post("/recordings/{rid}/uploads", response_model=RecordingOut, status_code=201)
def replace_video(rid: uuid.UUID, body: FileIn, request: Request, db: Session = DB, actor: User = Write) -> RecordingOut:
    """换一个视频文件（传错了或文件损坏）。只能在提交处理前进行，已标的分段会清空。"""
    rec = _get(db, rid)
    if rec.status not in ("uploading", "uploaded"):
        raise HTTPException(409, "已提交处理或已取消的录像不能换文件")
    ext = _check_file(body)
    _abort_open(db, rec)
    _drop_video(db, rec)
    rec.status, rec.segments, rec.objection_times, rec.exclusions = "uploading", [], [], []
    if rec.mode == "live":
        db.get(AuditionSheet, rec.sheet_id).objections = []
    rec.main_duration_ms = rec.video_duration_ms = None
    u = _open_upload(db, rec, body, ext, actor)
    _log(db, request, actor, "recording_replace_video", "recording", rec.id, upload_id=str(u.id))
    db.commit()
    return _out(db, rec)


@router.put("/recordings/{rid}/segments", response_model=RecordingOut)
def set_segments(rid: uuid.UUID, body: SegmentsIn, request: Request, db: Session = DB, actor: User = Write) -> RecordingOut:
    rec = _get(db, rid)
    if rec.status != "uploaded":
        raise HTTPException(409, "视频上传完成后、提交处理前才能标分段")
    if rec.mode != "audition":
        raise HTTPException(409, "录播没有题单和分段，请标注观众异议和排除时段")
    sheet = db.get(AuditionSheet, rec.sheet_id)
    qs, objs = sheet.questions, sheet.objections
    if len(body.question_starts_ms) != len(qs):
        raise HTTPException(422, f"须标出全部 {len(qs)} 道知识题的起点")
    if len(body.objection_offsets_ms) != len(objs):
        raise HTTPException(422, f"须给出全部 {len(objs)} 条异议的时间")
    points = [body.main_start_ms, *body.question_starts_ms, body.reading_start_ms]
    if any(b <= a for a, b in zip(points, points[1:])):
        raise HTTPException(422, "起点须按 主体段 → 知识题 1–N → 朗读 的顺序严格递增")
    if body.reading_start_ms >= (rec.video_duration_ms or 0):
        raise HTTPException(422, "朗读段起点超出视频时长")
    main_len = points[1] - body.main_start_ms  # 主体段到下一段（第一道知识题，没有知识题时为朗读段）起点
    offs = body.objection_offsets_ms
    if offs and (any(b <= a for a, b in zip(offs, offs[1:])) or offs[0] <= 0 or offs[-1] >= main_len):  # 题单没有异议时为空
        raise HTTPException(422, "异议时间须落在主体段内并严格递增")
    ends = [*points[1:], rec.video_duration_ms]
    names = ["main", *[f"question:{q['question_id']}" for q in qs], "reading"]
    rec.segments = [{"segment": n, "start_ms": s, "end_ms": e} for n, s, e in zip(names, points, ends)]
    rec.objection_times = [
        {"objection_id": o["objection_id"], "at_ms": t, "video_ms": body.main_start_ms + t, "sheet_at_ms": o["at_ms"]}
        for o, t in zip(objs, offs)
    ]
    rec.main_duration_ms = main_len
    _log(db, request, actor, "recording_segments", "recording", rec.id, main_start_ms=body.main_start_ms, main_duration_ms=main_len)
    db.commit()
    return _out(db, rec)


@router.put("/recordings/{rid}/live-marks", response_model=RecordingOut)
def set_live_marks(rid: uuid.UUID, body: LiveMarksIn, request: Request, db: Session = DB, actor: User = Write) -> RecordingOut:
    """录播标注（C37）：整段视频都是主体段，不截取、没有朗读段。员工看录播标出主播回应过的真实观众问题，
    以及不是主播本人在讲的时段（排除后不参与评分）。两项都可以为空，但须提交一次，表示已看过。"""
    rec = _get(db, rid)
    if rec.status != "uploaded":
        raise HTTPException(409, "视频上传完成后、提交处理前才能标注")
    if rec.mode != "live":
        raise HTTPException(409, "按题单录的试镜请标分段")
    total = rec.video_duration_ms or 0
    ex = sorted(((x.start_ms, x.end_ms) for x in body.exclusions))
    if any(a >= b or b > total for a, b in ex) or any(b1 > a2 for (_, b1), (a2, _) in zip(ex, ex[1:])):
        raise HTTPException(422, "排除时段须起点早于终点、落在视频时长内，且互不重叠")
    objs = sorted(body.objections, key=lambda o: o.video_ms)
    times = [o.video_ms for o in objs]
    if any(t >= total for t in times) or len(set(times)) != len(times):
        raise HTTPException(422, "观众异议的时间须落在视频时长内，且互不相同")
    kept = total - sum(b - a for a, b in ex)
    if kept < 60_000:
        raise HTTPException(422, "排除后主播本人讲解不足 1 分钟，无法评分")
    sheet = db.get(AuditionSheet, rec.sheet_id)
    ids = [str(uuid.uuid4()) for _ in objs]
    sheet.objections = [{"objection_id": i, "text": o.text.strip(), "at_ms": o.video_ms} for i, o in zip(ids, objs)]
    rec.segments = [{"segment": "main", "start_ms": 0, "end_ms": total}]
    rec.objection_times = [{"objection_id": i, "at_ms": o.video_ms, "video_ms": o.video_ms} for i, o in zip(ids, objs)]
    rec.exclusions = [{"start_ms": a, "end_ms": b} for a, b in ex]
    rec.main_duration_ms = kept
    _log(db, request, actor, "recording_live_marks", "recording", rec.id, objections=len(objs), exclusions=len(ex), main_duration_ms=kept)
    db.commit()
    return _out(db, rec)


def _ready(db: Session, rec: Recording) -> None:
    problems = readiness.blockers(db, db.get(AuditionSheet, rec.sheet_id), get_providers(), live=rec.mode == "live")
    if problems:
        raise HTTPException(422, "暂不能处理：" + "；".join(problems))


@router.post("/recordings/{rid}/submit", response_model=RecordingOut)
def submit(rid: uuid.UUID, request: Request, db: Session = DB, actor: User = Write) -> RecordingOut:
    rec = _get(db, rid)
    if rec.status != "uploaded":
        raise HTTPException(409, "只有已上传、未提交的录像可以提交")
    if not rec.segments:
        raise HTTPException(422, "请先标注观众异议和排除时段（没有也要确认一次）" if rec.mode == "live" else "请先标出各段起点和异议时间")
    if db.get(ConsentRecord, rec.consent_record_id) is None:
        raise HTTPException(422, "缺少书面同意登记，不能处理（C30）")
    get_candidate(db, rec.candidate_id)  # 候选人已申请删除的不能再处理
    _ready(db, rec)
    rec.status, rec.submitted_at = "submitted", _now()
    _log(db, request, actor, "recording_submit", "recording", rec.id)
    db.commit()
    orchestrator.start(rec.id)  # rq：入队后立即返回；inline：同步处理完再返回
    db.refresh(rec)
    return _out(db, rec)


@router.post("/recordings/{rid}/reprocess", response_model=RecordingOut)
def reprocess(rid: uuid.UUID, request: Request, db: Session = DB, actor: User = Write) -> RecordingOut:
    """处理失败的录像重新处理（例如供应商故障恢复后）。清掉各轮结果，从媒体准备开始。
    卡在“已提交 / 处理中”超过设定时长的（断电、重启中断）也可以重新处理。"""
    rec = _get(db, rid)
    started = rec.processing_started_at or rec.submitted_at
    stuck = (rec.status in ("submitted", "processing") and started is not None
             and _now() - started > timedelta(minutes=get_settings().stuck_after_min))
    if rec.status != "failed" and not stuck:
        raise HTTPException(409, "只有处理失败或处理中断（超时）的录像可以重新处理")
    _ready(db, rec)
    for run in db.scalars(select(PipelineRun).where(PipelineRun.recording_id == rec.id)):
        db.delete(run)
    rec.status, rec.failure_reason, rec.finished_at, rec.processing_started_at = "submitted", None, None, None
    _log(db, request, actor, "recording_reprocess", "recording", rec.id)
    db.commit()
    orchestrator.start(rec.id)
    db.refresh(rec)
    return _out(db, rec)


@router.post("/recordings/{rid}/cancel", response_model=RecordingOut)
def cancel(rid: uuid.UUID, request: Request, db: Session = DB, actor: User = Write) -> RecordingOut:
    """取消：删除已上传的视频，题单恢复为未使用。"""
    rec = _get(db, rid)
    if rec.status not in ("uploading", "uploaded"):
        raise HTTPException(409, "已提交处理的录像不能取消")
    _abort_open(db, rec)
    _drop_video(db, rec)
    rec.status = "cancelled"
    db.get(AuditionSheet, rec.sheet_id).status = "void" if rec.mode == "live" else "issued"  # 录播的内部记录随录像作废
    _log(db, request, actor, "recording_cancel", "recording", rec.id)
    db.commit()
    return _out(db, rec)


# ───────────── 评委人工打分（T39） ─────────────


class HumanScoreIn(BaseModel):
    score: float
    note: str | None = Field(default=None, max_length=500)


class HumanScoresIn(BaseModel):
    scores: dict[str, HumanScoreIn]


class HumanReviewOut(BaseModel):
    status: str
    items: list[dict]
    scores: dict[str, dict]


HumanWrite = Depends(require(Perm.human_score))


@router.get("/recordings/{rid}/human-review", response_model=HumanReviewOut)
def human_review(rid: uuid.UUID, db: Session = DB, _: User = HumanWrite) -> HumanReviewOut:
    rec = _get(db, rid)
    return HumanReviewOut(status=rec.status, items=human.pending_items(db, rec) if rec.status == "awaiting_human" else [],
                          scores=rec.human_scores or {})


@router.put("/recordings/{rid}/human-scores", response_model=HumanReviewOut)
def human_scores(rid: uuid.UUID, body: HumanScoresIn, request: Request, db: Session = DB, actor: User = HumanWrite) -> HumanReviewOut:
    rec = db.scalar(select(Recording).where(Recording.id == rid).with_for_update())
    if rec is None:
        raise HTTPException(404, "录像不存在")
    ready = human.submit(db, rec, {k: v.model_dump() for k, v in body.scores.items()}, actor)
    _log(db, request, actor, "human_scores", "recording", rec.id,
         **{"items": {k: v.score for k, v in body.scores.items()}, "rounds_completed": ready})
    db.commit()
    if rec.status == "processing":
        orchestrator.after_round(str(rec.id))
    db.refresh(rec)
    return human_review(rid, db, actor)


# ───────────── 分片上传 ─────────────


def _upload(db: Session, uid: uuid.UUID) -> UploadSession:
    u = db.get(UploadSession, uid)
    if u is None:
        raise HTTPException(404, "上传不存在")
    return u


@router.get("/uploads/{uid}", response_model=UploadOut)
def upload_status(uid: uuid.UUID, db: Session = DB, _: User = Write) -> UploadOut:
    """断点续传：返回已收到的分片，客户端只补传缺的。"""
    return _upload_out(_upload(db, uid))


@router.put("/uploads/{uid}/parts/{part_no}", response_model=UploadOut)
async def upload_part(
    uid: uuid.UUID, part_no: int, request: Request, db: Session = DB, _: User = Write,
    x_content_sha256: str | None = Header(default=None),
) -> UploadOut:
    u = _upload(db, uid)
    if u.status != "open":
        raise HTTPException(409, "上传已结束")
    count = math.ceil(u.total_size / u.part_size)
    if not 1 <= part_no <= count:
        raise HTTPException(422, f"分片编号应为 1–{count}")
    expect = u.part_size if part_no < count else u.total_size - u.part_size * (count - 1)
    data = await request.body()
    if len(data) != expect:
        raise HTTPException(422, f"第 {part_no} 片应为 {expect} 字节，实际 {len(data)}")
    digest = hashlib.sha256(data).hexdigest()
    if x_content_sha256 and x_content_sha256.lower() != digest:
        raise HTTPException(422, "分片校验失败，请重传")
    existing = next((p for p in u.parts if p["part_no"] == part_no), None)
    if existing and existing["sha256"] == digest:
        return _upload_out(u)  # 重复上传同一片：幂等
    etag = get_storage().upload_part(u.storage_key, u.multipart_upload_id, part_no, data)
    u.parts = [p for p in u.parts if p["part_no"] != part_no] + [{"part_no": part_no, "etag": etag, "size": len(data), "sha256": digest}]
    db.commit()
    return _upload_out(u)


@router.post("/uploads/{uid}/complete", response_model=RecordingOut)
def complete_upload(uid: uuid.UUID, request: Request, db: Session = DB, actor: User = Write) -> RecordingOut:
    u = _upload(db, uid)
    if u.status != "open":
        raise HTTPException(409, "上传已结束")
    count = math.ceil(u.total_size / u.part_size)
    missing = sorted(set(range(1, count + 1)) - {p["part_no"] for p in u.parts})
    if missing:
        raise HTTPException(422, f"还缺 {len(missing)} 个分片：{missing[:10]}")
    rec = db.get(Recording, u.recording_id)
    storage = get_storage()
    storage.complete_multipart(u.storage_key, u.multipart_upload_id, [Part(p["part_no"], p["etag"]) for p in u.parts])
    try:
        info = probe(storage.probe_location(u.storage_key))
        if not (info.has_video and info.has_audio):
            raise ProbeError("视频须同时包含画面和声音")
    except ProbeError as exc:
        storage.delete(u.storage_key)
        u.status = "aborted"
        _log(db, request, actor, "upload_rejected", "upload", u.id, reason=str(exc))
        db.commit()
        raise HTTPException(422, f"{exc}，请检查文件后重新上传") from exc
    u.status, u.completed_at = "completed", _now()
    db.add(MediaAsset(
        recording_id=rec.id, kind="raw_video", storage_key=u.storage_key, size_bytes=u.total_size, content_type=u.content_type,
        original_filename=u.filename, duration_ms=info.duration_ms, encrypted=storage.encrypted,
        retention_until=_now() + timedelta(days=get_settings().retention_days),  # 未录用者到期删除（里程碑 4 执行）
    ))
    rec.status, rec.video_duration_ms = "uploaded", info.duration_ms
    _log(db, request, actor, "upload_complete", "recording", rec.id, upload_id=str(u.id), size=u.total_size, duration_ms=info.duration_ms)
    db.commit()
    return _out(db, rec)


@router.post("/uploads/{uid}/abort", response_model=UploadOut)
def abort_upload(uid: uuid.UUID, request: Request, db: Session = DB, actor: User = Write) -> UploadOut:
    u = _upload(db, uid)
    if u.status != "open":
        raise HTTPException(409, "上传已结束")
    get_storage().abort_multipart(u.storage_key, u.multipart_upload_id)
    u.status = "aborted"
    _log(db, request, actor, "upload_abort", "upload", u.id)
    db.commit()
    return _upload_out(u)
