"""[S3-SIM] Signed, time-limited download links (doc 15 AM-7, simulating presigned GET URLs).

Issuing a link is local signing; no storage call (AM-4). The signature binds bucket, key,
version id, filename and expiry with HMAC-SHA256, so changing any of them invalidates it.
Anyone holding a valid link can use it until it expires, as with a real presigned URL.
"""

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from urllib.parse import quote, urlencode

DOWNLOAD_ROUTE = "/api/sim-s3"
_MAX_EXPIRES_DIGITS = 12  # Unix seconds stay 10 digits until the year 2286


@dataclass(frozen=True)
class SignedLink:
    url: str
    expires_at: int  # Unix seconds
    expires_in: int


def _canonical(bucket: str, key: str, version_id: str, filename: str, expires: int) -> bytes:
    # JSON keeps field boundaries unambiguous whatever characters the values contain.
    return json.dumps(["GET", bucket, key, version_id, filename, expires], ensure_ascii=False).encode("utf-8")


def signature(secret: str, bucket: str, key: str, version_id: str, filename: str, expires: int) -> str:
    mac = hmac.new(secret.encode("utf-8"), _canonical(bucket, key, version_id, filename, expires), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()).rstrip(b"=").decode("ascii")


def sign_download(
    *,
    secret: str,
    base_url: str,
    bucket: str,
    key: str,
    version_id: str,
    filename: str,
    now: int,
    ttl_seconds: int,
) -> SignedLink:
    expires = now + ttl_seconds
    query = urlencode(
        {
            "versionId": version_id,
            "filename": filename,
            "expires": expires,
            "signature": signature(secret, bucket, key, version_id, filename, expires),
        }
    )
    path = f"{DOWNLOAD_ROUTE}/{quote(bucket, safe='')}/{quote(key, safe='/')}"
    return SignedLink(url=f"{base_url.rstrip('/')}{path}?{query}", expires_at=expires, expires_in=ttl_seconds)


def verify_download(
    *,
    secret: str,
    bucket: str,
    key: str,
    version_id: str | None,
    filename: str | None,
    expires: str | None,
    sig: str | None,
    now: int,
) -> bool:
    """True only for an untampered, unexpired link. Expiry is checked at request time."""
    if not (version_id and filename is not None and expires and sig):
        return False
    # Only the canonical form the signer writes: ASCII digits, no leading zeros, bounded length.
    canonical = expires.isascii() and expires.isdigit() and len(expires) <= _MAX_EXPIRES_DIGITS
    if not canonical or expires != str(int(expires)):
        return False
    expected = signature(secret, bucket, key, version_id, filename, int(expires))
    # Bytes, so any client-supplied text compares in constant time without raising.
    if not hmac.compare_digest(expected.encode("ascii"), sig.encode("utf-8", "surrogatepass")):
        return False
    return now <= int(expires)


def content_disposition(filename: str) -> str:
    """`attachment` with an ASCII fallback and the RFC 5987 UTF-8 name (doc 03 W3)."""
    fallback = "".join(c if c.isascii() and c.isprintable() and c not in '"\\' else "_" for c in filename) or "download"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"
