"""导出 OpenAPI 结构，供前端生成类型：python backend/scripts/export_openapi.py frontend/src/api/openapi.json"""
import base64
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://unused@localhost/unused")
for k in ("APP_SESSION_KEY", "APP_DATA_KEY", "APP_HASH_KEY"):
    os.environ.setdefault(k, base64.b64encode(b"\0" * 32).decode())

from app.main import create_app  # noqa: E402

out = Path(sys.argv[1])
out.write_text(json.dumps(create_app().openapi(), ensure_ascii=False, indent=1), "utf-8")
print(f"已写入 {out}")
