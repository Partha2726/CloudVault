"""Standard error body {"error": {"code", "message", "details"}} (doc 05.1, 05.2)."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.storage.base import StorageError, StorageLimitExceeded

logger = logging.getLogger("cloudvault.errors")


class AppError(Exception):
    def __init__(self, code: str, status: int, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message
        self.details = details or {}


def error_response(status: int, code: str, message: str, details: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


# Framework-raised HTTP errors mapped onto the closed code set (doc 05.2).
_HTTP_CODES = {401: "UNAUTHORIZED", 404: "NOT_FOUND", 429: "RATE_LIMITED"}
_HTTP_MESSAGES = {
    404: "Not found",
    405: "Method not allowed",
    413: "Request body is too large",
    429: "Too many requests; try again later",
}


def _clean_msg(msg: str) -> str:
    return msg.removeprefix("Value error, ")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [{"loc": list(e["loc"]), "msg": _clean_msg(e["msg"])} for e in exc.errors()]
        # A single problem (e.g. the AM-5 password rule) becomes the top-level message.
        message = fields[0]["msg"] if len(fields) == 1 else "Invalid request"
        return error_response(422, "VALIDATION_ERROR", message, {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "VALIDATION_ERROR")
        message = _HTTP_MESSAGES.get(exc.status_code, str(exc.detail))
        return error_response(exc.status_code, code, message)

    @app.exception_handler(StorageLimitExceeded)
    async def _storage_full(_: Request, __: StorageLimitExceeded) -> JSONResponse:
        return error_response(507, "STORAGE_LIMIT_EXCEEDED", "The simulated storage limit has been reached")

    @app.exception_handler(StorageError)
    async def _storage_error(request: Request, exc: StorageError) -> JSONResponse:
        # Routers handle expected cases (missing versions, delete markers) themselves; anything
        # reaching here is a storage failure. Details stay in the server log.
        logger.warning("Storage error %s on %s %s", exc.code, request.method, request.url.path)
        return error_response(502, "STORAGE_ERROR", "Storage operation failed")

    @app.exception_handler(OperationalError)
    async def _db_down(_: Request, __: OperationalError) -> JSONResponse:
        return error_response(503, "DB_UNAVAILABLE", "Database unavailable")


def register_unhandled_error_middleware(app: FastAPI) -> None:
    """Unexpected exceptions become 500 INTERNAL_ERROR (doc 15 AM-6).

    The exception and request method/path are logged server-side. The client gets only a
    generic message: no stack trace, exception type or exception text. Request bodies,
    headers and query strings are never logged (they can hold tokens or file data).
    """

    @app.middleware("http")
    async def _unhandled(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception:
            logger.exception("Unhandled error on %s %s", request.method, request.url.path)
            return error_response(500, "INTERNAL_ERROR", "Internal server error")
