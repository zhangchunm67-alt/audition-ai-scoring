"""压测（A2）：5 条录像同时提交，Redis 队列 + 多个 worker，Mock 供应商注入延迟、并发上限和随机失败，测“提交 → 出报告”的耗时。

真实耗时无法在测试里等 30 分钟，所以把供应商延迟按 SCALE 缩小，结果再乘回 SCALE 估算真实耗时。
本地计算（ffmpeg 抽帧、声学特征）也会被乘上 SCALE，因此估算偏保守。

延迟假设（真实值，均可用参数覆盖）：
  语音识别：耗时 = 音频时长 × 0.15（文件转写）       大模型：每次调用 15 秒，所有 worker 合计同时最多 8 个调用
  语音评测：10 秒                                     视觉：每次调用 30 秒          笑声检测：5 秒
  随机失败率：每次调用 3%（单次调用再试 2 次，仍失败整轮重试 2 次）

用法：E2E_ADMIN_URL=postgresql://audition:audition@localhost/postgres .venv/bin/python scripts/load_test.py
"""
from __future__ import annotations

import argparse
import base64
import os
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument("--recordings", type=int, default=5)
ap.add_argument("--workers", type=int, default=5)
ap.add_argument("--scale", type=float, default=10.0)
ap.add_argument("--llm-s", type=float, default=15.0)
ap.add_argument("--llm-limit", type=int, default=8)
ap.add_argument("--asr-rtf", type=float, default=0.15)
ap.add_argument("--eval-s", type=float, default=10.0)
ap.add_argument("--vision-s", type=float, default=30.0)
ap.add_argument("--laugh-s", type=float, default=5.0)
ap.add_argument("--fail-rate", type=float, default=0.03)
ap.add_argument("--budget-min", type=float, default=30.0)
args = ap.parse_args()

DB_ADMIN = os.environ.get("E2E_ADMIN_URL", "postgresql://audition:audition@localhost/postgres")
DB = "audition_load"
tmp = Path(tempfile.mkdtemp(prefix="audition-load-"))
k = args.scale
env = {
    "DATABASE_URL": f"postgresql+psycopg://audition:audition@localhost/{DB}",
    "APP_SESSION_KEY": base64.b64encode(os.urandom(32)).decode(), "APP_DATA_KEY": base64.b64encode(os.urandom(32)).decode(),
    "APP_HASH_KEY": base64.b64encode(os.urandom(32)).decode(), "APP_COOKIE_SECURE": "false",
    "APP_STORAGE": "local", "APP_STORAGE_DIR": str(tmp / "storage"), "APP_UPLOAD_PART_BYTES": str(8 * 1024 * 1024),
    "APP_QUEUE": "rq", "APP_REDIS_URL": "redis://localhost:6379/5",
    "APP_MOCK_ASR_RTF": str(args.asr_rtf / k), "APP_MOCK_LATENCY_LLM": str(args.llm_s / k), "APP_MOCK_LATENCY_EVAL": str(args.eval_s / k),
    "APP_MOCK_LATENCY_VISION": str(args.vision_s / k), "APP_MOCK_LATENCY_LAUGH": str(args.laugh_s / k), "APP_MOCK_FAIL_RATE": str(args.fail_rate),
    "APP_RETRY_BACKOFF_S": f"{5 / k},{20 / k}", "APP_CALL_RETRY_BACKOFF_S": f"{1 / k},{3 / k}", "APP_LIMIT_LLM": str(args.llm_limit),
}
os.environ.update(env)
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

import psycopg  # noqa: E402
from redis import Redis  # noqa: E402

with psycopg.connect(DB_ADMIN, autocommit=True) as c:
    c.execute(f"DROP DATABASE IF EXISTS {DB}")
    c.execute(f"CREATE DATABASE {DB}")
Redis.from_url(env["APP_REDIS_URL"]).flushdb()
py = str(ROOT / ".venv" / "bin" / "python")
subprocess.run([py, "-m", "alembic", "upgrade", "head"], cwd=ROOT / "backend", check=True, capture_output=True)
video = tmp / "full.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=5:duration=1030", "-f", "lavfi", "-i",
                "sine=frequency=220:duration=1030", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "32k",
                "-shortest", str(video)], check=True)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.cli import create_user, seed_demo  # noqa: E402
from app.db import get_engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.entities import PipelineRun, Product, Recording, Report, RubricVersion  # noqa: E402

with Session(get_engine()) as db:
    seed_demo(db)
    create_user(db, "load-admin", "admin", "压测管理员", "load-password-1")
    create_user(db, "load-hr", "hr", "压测 HR", "load-password-1")
    pid, rid = str(db.scalar(select(Product.id))), str(db.scalar(select(RubricVersion.id)))

app = create_app()
H = {"X-Requested-With": "fetch"}
admin, hr = TestClient(app, headers=H), TestClient(app, headers=H)
admin.post("/api/auth/login", json={"username": "load-admin", "password": "load-password-1"})
hr.post("/api/auth/login", json={"username": "load-hr", "password": "load-password-1"})
data = video.read_bytes()
SEG = {"main_start_ms": 5000, "question_starts_ms": [605000 + i * 60000 for i in range(6)], "reading_start_ms": 965000,
       "objection_offsets_ms": [240000, 330000, 420000, 480000]}
recs = []
for i in range(args.recordings):
    cand = hr.post("/api/candidates", json={"name": f"压测候选人{i}"}).json()
    cons = hr.post(f"/api/candidates/{cand['id']}/consents", data={"consent_text_version": "v1", "signed_on": date.today().isoformat()}).json()
    sheet = admin.post("/api/sheets", json={"product_id": pid, "rubric_version_id": rid}).json()
    rec = hr.post("/api/recordings", json={"candidate_id": cand["id"], "sheet_id": sheet["id"], "consent_record_id": cons["id"], "audience": "new_trial",
                                          "props_available": True, "filename": "full.mp4", "content_type": "video/mp4", "size_bytes": len(data)}).json()
    up = rec["upload"]
    for n in range(1, up["part_count"] + 1):
        hr.put(f"/api/uploads/{up['id']}/parts/{n}", content=data[(n - 1) * up["part_size"]: n * up["part_size"]])
    assert hr.post(f"/api/uploads/{up['id']}/complete").status_code == 200
    assert hr.put(f"/api/recordings/{rec['id']}/segments", json=SEG).status_code == 200
    recs.append(rec["id"])

workers = [subprocess.Popen([py, "-m", "app.cli", "worker"], cwd=ROOT / "backend", env={**os.environ}, stdout=subprocess.DEVNULL,
                            stderr=open(tmp / f"worker{i}.log", "w")) for i in range(args.workers)]
try:
    time.sleep(2)
    t0 = time.time()
    for r in recs:  # 同时提交
        assert hr.post(f"/api/recordings/{r}/submit").status_code == 200
    deadline = t0 + args.budget_min * 60 / k * 3
    while time.time() < deadline:
        with Session(get_engine()) as db:
            st = [db.get(Recording, r).status for r in recs]
        if all(s in ("done", "failed") for s in st):
            break
        time.sleep(1)
    with Session(get_engine()) as db:
        rows = []
        for r in recs:
            rec = db.get(Recording, r)
            runs = db.scalars(select(PipelineRun).where(PipelineRun.recording_id == rec.id)).all()
            rep = db.scalar(select(Report).where(Report.recording_id == rec.id))
            dur = (rec.finished_at - rec.submitted_at).total_seconds() if rec.finished_at else None
            rows.append((r[:8], rec.status, dur, len(runs), sum(x.retry_count for x in runs), rep.label if rep else "—"))
finally:
    for w in workers:
        w.terminate()
    for w in workers:
        w.wait(10)

print(f"\n{args.recordings} 条同时提交，{args.workers} 个 worker，大模型并发上限 {args.llm_limit}，随机失败率 {args.fail_rate:.0%}，缩放 1/{k:g}")
print(f"{'录像':10}{'状态':8}{'实测秒':>8}{'估算真实分钟':>12}{'轮数':>6}{'整轮重试':>8}  标签")
for rid_, status, dur, nruns, retries, label in rows:
    est = f"{dur * k / 60:.1f}" if dur else "—"
    print(f"{rid_:10}{status:8}{(f'{dur:.1f}' if dur else '—'):>8}{est:>12}{nruns:>6}{retries:>8}  {label}")
durs = [d for _, s, d, *_ in rows if d is not None and s == "done"]
ok = len(durs) == len(rows)
if durs:
    p95 = sorted(durs)[max(0, int(round(0.95 * len(durs))) - 1)] * k / 60
    print(f"估算真实耗时：中位数 {statistics.median(durs) * k / 60:.1f} 分钟，p95 {p95:.1f} 分钟，最长 {max(durs) * k / 60:.1f} 分钟（目标 ≤ {args.budget_min:g} 分钟）")
    ok = ok and max(durs) * k / 60 <= args.budget_min
with psycopg.connect(DB_ADMIN, autocommit=True) as c:
    get_engine().dispose()
    c.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
print("结果：" + ("通过" if ok else "未通过"))
sys.exit(0 if ok else 1)
