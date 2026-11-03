from fastapi import APIRouter, Depends, HTTPException

from ..content.recording_rules import RULES
from ..models.entities import User
from ..security.rbac import Perm
from .deps import require

router = APIRouter(prefix="/recording-rules", tags=["录制规则"])


@router.get("/{version}")
def get_rules(version: str, _: User = Depends(require(Perm.sheet_read))) -> dict:
    if version not in RULES:
        raise HTTPException(404, "录制规则版本不存在")
    return {"version": version, **RULES[version]}
