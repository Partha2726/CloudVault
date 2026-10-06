"""HTTP hardening (T24): security headers, a body cap for non-upload routes, log redaction.

Pure ASGI middleware, so streaming upload bodies pass through untouched.
"""

import logging
import re

from fastapi import HTTPException
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import error_response

# JSON and empty-bodied routes. Real requests are well under 1 KiB; the cap stops a client
# from making the server buffer an unbounded body before validation runs.
NON_UPLOAD_BODY_LIMIT = 64 * 1024
# The two upload routes stream and cap their own bodies (validation.read_upload).
_UPLOAD_ROUTES = re.compile(r"^/api/documents(/[^/]+/versions)?/?$")

# Swagger UI and ReDoc load scripts and styles; they keep every header except the CSP.
_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")
_API_CSP = "default-src 'none'; frame-ancestors 'none'"


_TOO_LARGE = "Request body is too large"


class BodySizeLimitMiddleware:
    """413 for a declared or streamed body over the limit, on every route except uploads."""

    def __init__(self, app: ASGIApp, limit: int = NON_UPLOAD_BODY_LIMIT):
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or (scope["method"] == "POST" and _UPLOAD_ROUTES.match(scope["path"])):
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.limit:
            await error_response(413, "VALIDATION_ERROR", _TOO_LARGE)(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:  # chunked or understated Content-Length
                    # FastAPI re-raises HTTPException from body parsing; the app's handler renders it.
                    raise HTTPException(413, _TOO_LARGE)
            return message

        await self.app(scope, limited_receive, send)


class SecurityHeadersMiddleware:
    """Headers for an API that serves JSON and attachment downloads, never pages to frame or sniff.

    A header a route sets itself (the signed route's Cache-Control) is kept.
    """

    def __init__(self, app: ASGIApp, hsts: bool = False):
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_doc_page = scope["path"].startswith(_DOC_PATHS)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                # Signed download URLs carry their signature in the query string.
                headers.setdefault("Referrer-Policy", "no-referrer")
                if not is_doc_page:
                    headers.setdefault("Content-Security-Policy", _API_CSP)
                    headers.setdefault("Cache-Control", "no-store")
                if self.hsts:
                    headers.setdefault("Strict-Transport-Security", "max-age=31536000")
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RedactQueryStrings(logging.Filter):
    """Drop query strings from uvicorn access-log lines.

    A signed download URL is a credential until it expires (doc 09.1: never log presigned
    URLs; AM-6: never log query strings). The access log keeps method, path and status.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) and "?" in args[2]:
            record.args = (*args[:2], args[2].split("?", 1)[0], *args[3:])
        return True


def install_access_log_redaction() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactQueryStrings) for f in access.filters):
        access.addFilter(RedactQueryStrings())
