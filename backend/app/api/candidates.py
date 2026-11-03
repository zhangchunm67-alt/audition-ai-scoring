"""候选人与书面同意登记（C30）。姓名、手机号加密存储，查看详情写审计。"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.entities import Candidate, ConsentRecord, MediaAsset, Recording, User
from ..security.crypto import decrypt, encrypt, lookup_hash
from ..security.rbac import Perm
from ..services import audit
from ..services.storage import get_storage
from ..settings import get_settings
from .deps import DB, require

router = APIRouter(prefix="/candidates", tags=["候选人"])
Read = Depends(require(Perm.report_read_all))
Write = Depends(require(Perm.recording_upload))
HIRING_ZH = {"undecided": "未定", "hired": "已录用", "not_hired": "未录用"}
SCAN_TYPES = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}
MAX_SCAN_BYTES = 10 * 1024 * 1024


def _aad(cid: uuid.UUID, field: str) -> bytes:
    return f"candidate:{cid}:{field}".encode()


def name_of(c: Candidate) -> str:
    return decrypt(c.name_enc, get_settings().data_key, aad=_aad(c.id, "name"))


def phone_of(c: Candidate) -> str | None:
    return decrypt(c.phone_enc, get_settings().data_key, aad=_aad(c.id, "phone")) if c.phone_enc else None


def mask(phone: str | None) -> str | None:
    return None if not phone else (phone[:3] + "****" + phone[-4:] if len(phone) >= 7 else "****")


class CandidateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    phone: str | None = Field(default=None, pattern=r"^[0-9 +-]{6,20}$")


class ConsentOut(BaseModel):
    id: uuid.UUID
    consent_text_version: str
    signed_on: date
    attachment_asset_id: uuid.UUID | None
    registered_at: datetime


class CandidateRow(BaseModel):
    id: uuid.UUID
    name: str
    phone_masked: str | None
    hiring_status: str
    consent_count: int
    recording_count: int
    created_at: datetime


class CandidateDetail(CandidateRow):
    phone: str | None
    consents: list[ConsentOut]
    linked_user_id: uuid.UUID | None = None


class HiringIn(BaseModel):
    hiring_status: str = Field(pattern=r"^(undecided|hired|not_hired)$")


def _counts(db: Session, cid: uuid.UUID) -> tuple[int, int]:
    nc = db.scalar(select(func.count()).select_from(ConsentRecord).where(ConsentRecord.candidate_id == cid))
    nr = db.scalar(select(func.count()).select_from(Recording).where(Recording.candidate_id == cid, Recording.status != "cancelled"))
    return nc, nr


def _row(db: Session, c: Candidate) -> CandidateRow:
    nc, nr = _counts(db, c.id)
    return CandidateRow(id=c.id, name=name_of(c), phone_masked=mask(phone_of(c)), hiring_status=c.hiring_status,
                        consent_count=nc, recording_count=nr, created_at=c.created_at)


def get_candidate(db: Session, cid: uuid.UUID) -> Candidate:
    c = db.get(Candidate, cid)
    if c is None or c.deleted_at is not None:
        raise HTTPException(404, "候选人不存在")
    return c


@router.get("", response_model=list[CandidateRow])
def list_candidates(phone: str | None = None, db: Session = DB, _: User = Read) -> list[CandidateRow]:
    q = select(Candidate).where(Candidate.deleted_at.is_(None)).order_by(Candidate.created_at.desc())
    if phone:
        q = q.where(Candidate.phone_hash == lookup_hash(phone, get_settings().hash_key))
    return [_row(db, c) for c in db.scalars(q.limit(500))]


@router.post("", response_model=CandidateRow, status_code=201)
def create_candidate(body: CandidateIn, request: Request, db: Session = DB, actor: User = Write) -> CandidateRow:
    s = get_settings()
    cid = uuid.uuid4()
    c = Candidate(
        id=cid, name_enc=encrypt(body.name.strip(), s.data_key, aad=_aad(cid, "name")),
        phone_enc=encrypt(body.phone.strip(), s.data_key, aad=_aad(cid, "phone")) if body.phone else None,
        phone_hash=lookup_hash(body.phone, s.hash_key) if body.phone else None,
    )
    db.add(c)
    db.flush()
    audit.record(db, request, actor_type="user", actor_id=str(actor.id), action="candidate_create", target_type="candidate", target_id=str(c.id))
    db.commit()
    return _row(db, c)


@router.get("/{cid}", response_model=CandidateDetail)
def get_detail(cid: uuid.UUID, request: Request, db: Session = DB, viewer: User = Read) -> CandidateDetail:
    c = get_candidate(db, cid)
    consents = db.scalars(select(ConsentRecord).where(ConsentRecord.candidate_id == cid).order_by(ConsentRecord.registered_at.desc()))
    out = CandidateDetail(**_row(db, c).model_dump(), phone=phone_of(c), linked_user_id=c.linked_user_id,
                          consents=[ConsentOut.model_validate(x, from_attributes=True) for x in consents])
    audit.record(db, request, actor_type="user", actor_id=str(viewer.id), action="candidate_view", target_type="candidate", target_id=str(cid))
    db.commit()
    return out


@router.patch("/{cid}/hiring", response_model=CandidateRow)
def set_hiring(cid: uuid.UUID, body: HiringIn, request: Request, db: Session = DB,
               actor: User = Depends(require(Perm.hiring_update))) -> CandidateRow:
    c = get_candidate(db, cid)
    before, c.hiring_status, c.hiring_status_by = c.hiring_status, body.hiring_status, actor.id
    audit.record(db, request, actor_type="user", actor_id=str(actor.id), action="hiring_update", target_type="candidate", target_id=str(cid),
                 before=before, after=body.hiring_status)
    db.commit()
    return _row(db, c)


class LinkIn(BaseModel):
    user_id: uuid.UUID | None  # None 表示解除关联


@router.put("/{cid}/linked-user", response_model=CandidateDetail)
def link_user(cid: uuid.UUID, body: LinkIn, request: Request, db: Session = DB,
              actor: User = Depends(require(Perm.hiring_update))) -> CandidateDetail:
    """把已录用的新主播账号关联到本人的试镜记录（C31）：关联后该账号只能看到本人记录。"""
    c = get_candidate(db, cid)
    if body.user_id is not None:
        u = db.get(User, body.user_id)
        if u is None or u.role != "anchor" or not u.is_active:
            raise HTTPException(422, "只能关联启用中的“新主播”角色账号")
    before, c.linked_user_id = c.linked_user_id, body.user_id
    audit.record(db, request, actor_type="user", actor_id=str(actor.id), action="candidate_link_user", target_type="candidate", target_id=str(cid),
                 before=str(before) if before else None, after=str(body.user_id) if body.user_id else None)
    db.commit()
    return get_detail(cid, request, db, actor)


@router.post("/{cid}/consents", response_model=ConsentOut, status_code=201)
async def register_consent(
    cid: uuid.UUID,
    request: Request,
    consent_text_version: str = Form(min_length=1, max_length=64),
    signed_on: date = Form(),
    attachment: UploadFile | None = File(default=None),
    db: Session = DB,
    actor: User = Write,
) -> ConsentOut:
    """登记“已取得候选人书面同意”：同意书版本、签署日期必填，扫描件可选（PDF / JPG / PNG，≤ 10 MB）。"""
    c = get_candidate(db, cid)
    if signed_on > datetime.now(timezone.utc).date():
        raise HTTPException(422, "签署日期不能晚于今天")
    rec = ConsentRecord(candidate_id=c.id, consent_text_version=consent_text_version.strip(), signed_on=signed_on, registered_by=actor.id)
    db.add(rec)
    db.flush()
    if attachment is not None and attachment.filename:
        ctype = attachment.content_type or ""
        if ctype not in SCAN_TYPES:
            raise HTTPException(422, "扫描件只支持 PDF、JPG、PNG")
        data = await attachment.read(MAX_SCAN_BYTES + 1)
        if len(data) > MAX_SCAN_BYTES:
            raise HTTPException(422, "扫描件不能超过 10 MB")
        key = f"candidates/{c.id}/consent/{rec.id}{SCAN_TYPES[ctype]}"
        storage = get_storage()
        storage.put(key, data, ctype)
        asset = MediaAsset(candidate_id=c.id, kind="consent_scan", storage_key=key, size_bytes=len(data), content_type=ctype,
                           original_filename=attachment.filename[:255], encrypted=storage.encrypted)
        db.add(asset)
        db.flush()
        rec.attachment_asset_id = asset.id
    audit.record(db, request, actor_type="user", actor_id=str(actor.id), action="consent_register", target_type="consent_record",
                 target_id=str(rec.id), candidate_id=str(c.id), version=rec.consent_text_version, has_attachment=rec.attachment_asset_id is not None)
    db.commit()
    return ConsentOut.model_validate(rec, from_attributes=True)
