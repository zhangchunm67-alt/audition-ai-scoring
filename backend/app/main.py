"""FastAPI 应用入口。uvicorn app.main:app"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import audit_logs, auth, products, redlines, rubrics, scripts, sheets, users
from .settings import get_settings

CSRF_HEADER = "x-requested-with"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="主播试镜 AI 评分系统", version="0.2.0", docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        # Cookie 会话 + SameSite=Strict；另外要求写操作带自定义头，跨站表单无法伪造
        if request.url.path.startswith("/api/") and request.method not in SAFE_METHODS:
            if request.headers.get(CSRF_HEADER) != "fetch":
                return JSONResponse({"detail": "缺少请求头 X-Requested-With: fetch"}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    for r in (auth, users, rubrics, products, scripts, redlines, sheets, audit_logs):
        app.include_router(r.router, prefix="/api")

    @app.get("/api/health", tags=["系统"])
    def health() -> dict:
        return {"status": "ok"}

    dist = Path(settings.frontend_dist) if settings.frontend_dist else None
    if dist and (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            return FileResponse(dist / "index.html")

    return app


def __getattr__(name: str):  # 懒加载，测试时可以先设置环境变量
    if name == "app":
        return create_app()
    raise AttributeError(name)
