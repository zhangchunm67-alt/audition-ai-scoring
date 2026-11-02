"""红线词表：只有合规能写，编号须与评分标准一致。"""
from tests.scoring.helpers import CONFIG_PATH

ENTRY = {"name": "承诺收益或保本", "keywords": ["稳赚不赔"], "correct": ["如实讲合同约定的给付"]}
FULL = {f"R{i}": ENTRY for i in range(1, 9)}


def _rubric(login):
    admin = login("admin")
    admin.post("/api/rubrics", json={"yaml_text": CONFIG_PATH.read_text("utf-8")})
    return admin


def test_compliance_creates_and_publishes(login):
    admin = _rubric(login)
    comp = login("compliance")
    r = comp.post("/api/redline-lexicons", json={"version": "lex-1", "content": FULL})
    assert r.status_code == 201 and r.json()["status"] == "draft"
    r2 = comp.post("/api/redline-lexicons", json={"version": "lex-2", "content": FULL})
    comp.post(f"/api/redline-lexicons/{r.json()['id']}/publish")
    comp.post(f"/api/redline-lexicons/{r2.json()['id']}/publish")
    st = {x["version"]: x["status"] for x in admin.get("/api/redline-lexicons").json()}
    assert st == {"lex-1": "retired", "lex-2": "published"}


def test_admin_cannot_edit_lexicon(login):
    admin = _rubric(login)
    assert admin.post("/api/redline-lexicons", json={"version": "lex-1", "content": FULL}).status_code == 403


def test_ids_must_match_rubric(login):
    _rubric(login)
    comp = login("compliance")
    partial = {k: v for k, v in FULL.items() if k != "R8"}
    r = comp.post("/api/redline-lexicons", json={"version": "lex-1", "content": partial})
    assert r.status_code == 422 and "R8" in r.json()["detail"]
    r = comp.post("/api/redline-lexicons", json={"version": "lex-1", "content": {**FULL, "R9": ENTRY}})
    assert r.status_code == 422 and "R9" in r.json()["detail"]
    assert comp.post("/api/redline-lexicons", json={"version": "lex-1", "content": {**FULL, "R1": {**ENTRY, "correct": []}}}).status_code == 422
