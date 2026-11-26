from fastapi import Request
from fastapi.responses import JSONResponse

from backend.logger import get_logger

logger = get_logger("errors")


class AppError(Exception):
    def __init__(self, message: str, code: str = "error", status: int = 400, details: dict | None = None):
        self.message = message
        self.code = code
        self.status = status
        self.details = details or {}
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, message: str = "资源不存在"):
        super().__init__(message, code="not_found", status=404)


class ValidationError(AppError):
    def __init__(self, message: str):
        super().__init__(message, code="validation_error", status=400)


class AIUnavailableError(AppError):
    def __init__(self, message: str = "AI 服务不可用"):
        super().__init__(message, code="ai_unavailable", status=503)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.warning("AppError %s: %s | path=%s", exc.code, exc.message, request.url.path)
    return JSONResponse(
        status_code=exc.status,
        content={"ok": False, "code": exc.code, "error": exc.message, "details": exc.details},
    )


async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"ok": False, "code": "internal_error", "error": "服务器内部错误，请查看日志"},
    )