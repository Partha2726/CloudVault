"""slowapi limiter (doc 09.1): in-memory, per instance.

Behind a proxy (Render) the client address comes from X-Forwarded-For only when uvicorn
runs with --proxy-headers (T26); otherwise every request shares the proxy's address.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

limiter = Limiter(key_func=get_remote_address)


def user_key(request: Request) -> str:
    """Per-user limit key. Set by `get_current_user`, which always runs before the limit check."""
    return f"user:{getattr(request.state, 'user_id', None) or get_remote_address(request)}"


# Doc 09.1: "upload 20/min/user" is one budget shared by every upload endpoint.
upload_limit = limiter.shared_limit("20/minute", scope="upload", key_func=user_key)
