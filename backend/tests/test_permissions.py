"""权限矩阵：每个角色对每类接口的访问结果。"""
import uuid

import pytest

from app.security.rbac import MATRIX, Perm, Role

X = str(uuid.uuid4())
CASES = [
    ("get", "/api/users", None, Perm.users_manage),
    ("post", "/api/users", {"username": "zzz", "display_name": "z", "role": "hr", "password": "0123456789"}, Perm.users_manage),
    ("patch", f"/api/users/{X}", {}, Perm.users_manage),
    ("get", "/api/rubrics", None, Perm.config_read),
    ("post", "/api/rubrics", {"yaml_text": "x: 1"}, Perm.config_write),
    ("post", f"/api/rubrics/{X}/publish", None, Perm.config_write),
    ("get", "/api/products", None, Perm.config_read),
    ("post", "/api/products", {"code": "p1", "name": "产品"}, Perm.config_write),
    ("get", f"/api/products/{X}/cards", None, Perm.config_read),
    ("post", f"/api/cards/{X}/publish", None, Perm.config_write),
    ("get", f"/api/products/{X}/objections", None, Perm.config_read),
    ("put", f"/api/questions/{X}", {"text": "t", "full_points": ["a"]}, Perm.config_write),
    ("put", f"/api/products/{X}/draw-rule", {}, Perm.config_write),
    ("get", "/api/reading-scripts", None, Perm.config_read),
    ("post", "/api/reading-scripts", {"title": "t", "text": "x"}, Perm.config_write),
    ("get", "/api/redline-lexicons", None, Perm.redline_read),
    ("post", f"/api/redline-lexicons/{X}/publish", None, Perm.redline_write),
    ("get", "/api/sheets", None, Perm.sheet_read),
    ("post", f"/api/sheets/{X}/void", None, Perm.sheet_write),
    ("get", "/api/audit-logs", None, Perm.audit_read),
]


@pytest.mark.parametrize("role", [r.value for r in Role])
def test_matrix(login, role):
    api = login(role)
    for method, path, body, perm in CASES:
        kw = {"json": body} if body is not None else {}
        status = getattr(api, method)(path, **kw).status_code
        if Role(role) in MATRIX[perm]:
            assert status not in (401, 403), (role, method, path, status)
        else:
            assert status == 403, (role, method, path, status)


def test_anonymous_gets_401(anon):
    for method, path, body, _ in CASES:
        kw = {"json": body} if body is not None else {}
        assert getattr(anon, method)(path, **kw).status_code == 401, path


def test_key_rules():
    assert MATRIX[Perm.redline_write] == {Role.compliance}  # PRD M1-5：仅合规可编辑红线词表
    assert Role.hr in MATRIX[Perm.report_read_all]  # C19：HR 看全部内容
    assert Role.anchor not in MATRIX[Perm.report_read_all] and Role.anchor in MATRIX[Perm.report_read_own]  # C31
