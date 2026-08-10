from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.db import initialize_database
from backend.config_api import router as config_router
from backend.dashboard_api import router as dashboard_router
from backend.promotions import router as promotions_router
from backend.batch_monitor import router as batch_monitor_router
from backend.app_revisions import router as app_revisions_router
from backend.reports_api import router as reports_router
from backend.tasks import router as tasks_router
from app_paths import FRONTEND_DIST

app = FastAPI(title="销售数据看板 API", version="2.0.1")
app.add_middleware(GZipMiddleware, minimum_size=500, compresslevel=6)
app.include_router(tasks_router)
app.include_router(reports_router)
app.include_router(config_router)
app.include_router(dashboard_router)
app.include_router(promotions_router)
app.include_router(batch_monitor_router)
app.include_router(app_revisions_router)
# Keep embedded runners and test clients usable even when they do not emit a lifespan event.
initialize_database()


@app.on_event("startup")
def startup(): initialize_database()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.middleware("http")
async def cache_headers(request: Request, call_next):
    upload_limits = {
        "/api/reports/performance": 105 * 1024 * 1024,
        "/api/reports/sales-history": 105 * 1024 * 1024,
    }
    path = request.url.path
    if path.startswith("/api/reports/source/"):
        upload_limit = 52 * 1024 * 1024
    elif path in {"/api/batch-monitor/batches", "/api/batch-monitor/shipments"}:
        upload_limit = 22 * 1024 * 1024
    elif path.startswith("/api/config/") and path.endswith("/upload"):
        upload_limit = 12 * 1024 * 1024
    else:
        upload_limit = upload_limits.get(path)
    content_length = request.headers.get("content-length")
    if upload_limit and content_length and content_length.isdigit() and int(content_length) > upload_limit:
        return JSONResponse({"detail": "请求体超过上传限制"}, status_code=413)
    response = await call_next(request)
    if request.url.path.startswith("/assets/") and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


if (FRONTEND_DIST / "index.html").exists():
    if (FRONTEND_DIST / "assets").exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "API 不存在")
        return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-store"})
