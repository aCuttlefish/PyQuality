import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import database
from backend.config import FRONTEND_DIR
from backend.errors import AppError, app_error_handler, unhandled_handler
from backend.logger import get_logger, log_request
from backend.routers import ai, analysis, chat, config as config_router, projects

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.get_conn()
    logger.info("PyQuality 服务启动")
    yield
    logger.info("PyQuality 服务关闭")


app = FastAPI(title="Python 代码质量检测平台", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, unhandled_handler)


@app.middleware("http")
async def request_logger(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration = (time.perf_counter() - start) * 1000
        log_request(request.method, request.url.path, 500, duration)
        raise
    duration = (time.perf_counter() - start) * 1000
    log_request(request.method, request.url.path, response.status_code, duration)
    return response


app.include_router(projects.router)
app.include_router(analysis.router)
app.include_router(ai.router)
app.include_router(chat.router)
app.include_router(config_router.router)


@app.get("/api/health")
def health():
    return {"ok": True, "service": "python-code-quality", "version": "2.0.0", "status": "running"}


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/{path:path}")
    def spa_fallback(path: str):
        if path.startswith("api/"):
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        candidate = FRONTEND_DIR / path
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIR / "index.html")