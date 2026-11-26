import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import accounts, auth, emails, health, rules, settings as settings_router, stats
from app.api.settings import load_settings_from_db
from app.core.config import set_db_overrides
from app.core.database import async_session_factory, engine
from app.core.encryption import ensure_encryption_key
from app.core.schema_patch import ensure_sqlite_columns
from app.models import Base
from app.worker.poller import poller_loop

# 前端构建产物目录（Docker 或本地 build 后存在）
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="MailAggregator Pro", version="0.1.0")

    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(accounts.router, prefix="/api")
    app.include_router(emails.router, prefix="/api")
    app.include_router(rules.router, prefix="/api")
    app.include_router(settings_router.router, prefix="/api")
    app.include_router(stats.router, prefix="/api")

    # 生产环境：提供前端静态资源与 SPA 回退
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static-root")

        index_html = STATIC_DIR / "index.html"
        if index_html.is_file():
            static_dir_resolved = STATIC_DIR.resolve()

            @app.get("/{full_path:path}")
            def serve_spa(full_path: str) -> FileResponse:
                # 未知的 /api/* 请求直接返回 404，而不是回退到 index.html
                if full_path == "api" or full_path.startswith("api/"):
                    raise HTTPException(status_code=404, detail="Not Found")
                # 禁止绝对路径与路径穿越，防止扫描器请求 //etc/shadow、//proc/self/xxx 等触发读系统文件导致 PermissionError / 轮询异常
                if not full_path or full_path.startswith("/") or ".." in full_path:
                    return FileResponse(str(index_html))
                try:
                    file = (STATIC_DIR / full_path).resolve()
                    if not file.is_relative_to(static_dir_resolved) or not file.is_file():
                        return FileResponse(str(index_html))
                    return FileResponse(str(file))
                except (ValueError, OSError):
                    return FileResponse(str(index_html))

    @app.on_event("startup")
    async def _ensure_db_tables() -> None:
        # Ensure a stable encryption key exists for password storage.
        ensure_encryption_key()

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await ensure_sqlite_columns(engine)

        async with async_session_factory() as db:
            set_db_overrides(await load_settings_from_db(db))

        app.state.poller_task = asyncio.create_task(poller_loop())

    @app.on_event("shutdown")
    async def _shutdown_background_tasks() -> None:
        task = getattr(app.state, "poller_task", None)
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        await engine.dispose()

    return app


app = create_app()

