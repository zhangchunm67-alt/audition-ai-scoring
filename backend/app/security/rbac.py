"""角色与权限矩阵。依据见 docs/decisions.md（C19、C31，以及 I9 的默认分工）。"""
from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    admin = "admin"  # 管理员：维护评分标准、卖点卡、题库，生成题单，管理账号
    compliance = "compliance"  # 合规：维护红线词表和正确说法
    calibrator = "calibrator"  # 校准员：只看抽中的样本（里程碑 6）
    hr = "hr"  # HR：看全部内容（C19）
    anchor = "anchor"  # 已录用新主播：只看本人记录（C31）


class Perm(str, Enum):
    config_read = "config.read"
    config_write = "config.write"
    redline_read = "redline.read"
    redline_write = "redline.write"
    sheet_read = "sheet.read"
    sheet_write = "sheet.write"
    users_manage = "users.manage"
    audit_read = "audit.read"
    recording_upload = "recording.upload"  # 登记候选人和授权、上传录像、标分段
    hiring_update = "hiring.update"  # 标记录用状态（决定未录用者的媒体到期删除）
    report_read_all = "report.read_all"  # 里程碑 5：全部报告与视频
    report_read_own = "report.read_own"  # 里程碑 5：本人记录
    calibration_manage = "calibration.manage"  # 建金标准集、分配校准员、裁决分歧
    calibration_score = "calibration.score"  # 给分到自己的样本背对背打分
    dashboard_read = "dashboard.read"  # 一致率看板、效率看板
    human_score = "human.score"  # 评委给机器评不了或须人工确认的条目打分（T39）


R = Role
MATRIX: dict[Perm, frozenset[Role]] = {
    Perm.config_read: frozenset({R.admin, R.compliance, R.hr, R.calibrator}),
    Perm.config_write: frozenset({R.admin}),
    Perm.redline_read: frozenset({R.admin, R.compliance, R.hr, R.calibrator}),
    Perm.redline_write: frozenset({R.compliance}),  # PRD M1-5：仅合规可编辑
    Perm.sheet_read: frozenset({R.admin, R.hr}),
    Perm.sheet_write: frozenset({R.admin}),
    Perm.users_manage: frozenset({R.admin}),
    Perm.audit_read: frozenset({R.admin}),
    Perm.recording_upload: frozenset({R.admin, R.hr}),
    Perm.hiring_update: frozenset({R.admin, R.hr}),
    Perm.report_read_all: frozenset({R.admin, R.hr}),
    Perm.report_read_own: frozenset({R.anchor}),
    Perm.calibration_manage: frozenset({R.admin}),
    Perm.calibration_score: frozenset({R.calibrator}),
    Perm.dashboard_read: frozenset({R.admin}),  # PRD 第 3 节：管理员看准确度看板
    Perm.human_score: frozenset({R.admin, R.hr}),  # 评委打分：HR 本就能看全部内容（C19）
}


def allowed(role: str, perm: Perm) -> bool:
    return Role(role) in MATRIX[perm]


def perms_of(role: str) -> list[str]:
    return sorted(p.value for p, roles in MATRIX.items() if Role(role) in roles)
