"""[S3-SIM] Signed download route: the simulated presigned GET (doc 15, AM-7).

Authorization comes only from the verified signature: bucket, key, version id, filename
and expiry are bound by HMAC. The route has no login dependency and ignores any
Authorization header or session; possession of an unexpired link is the credential,
exactly as with a real presigned URL.
"""

import time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.config import get_settings
from app.errors import AppError
from app.storage import get_storage
from app.storage.base import MethodNotAllowed, NoSuchKey, NoSuchVersion, ObjectStorage
from app.storage.signing import DOWNLOAD_ROUTE, content_disposition, verify_download

router = APIRouter(prefix=DOWNLOAD_ROUTE.removeprefix("/api"), tags=["simulated-s3"])


def epoch_now() -> int:
    return int(time.time())


def _access_denied() -> AppError:
    # One message for every failure, so callers learn nothing about which check failed.
    return AppError("ACCESS_DENIED", 403, "Request has expired or the signature is invalid")


@router.get("/{bucket}/{key:path}")
def signed_download(
    bucket: str,
    key: str,
    version_id: str | None = Query(None, alias="versionId"),
    filename: str | None = Query(None),
    expires: str | None = Query(None),
    signature: str | None = Query(None),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    valid = bucket == storage.bucket and verify_download(
        secret=get_settings().sim_signing_secret,
        bucket=bucket,
        key=key,
        version_id=version_id,
        filename=filename,
        expires=expires,
        sig=signature,
        now=epoch_now(),
    )
    if not valid:
        raise _access_denied()
    try:
        head, data = storage.get_object(key, version_id)
    except (NoSuchKey, NoSuchVersion, MethodNotAllowed) as exc:
        raise AppError("NOT_FOUND", 404, "The object version no longer exists") from exc
    return Response(
        content=data,
        media_type=head.content_type,
        headers={
            "Content-Disposition": content_disposition(filename),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "ETag": head.etag,
            "x-amz-version-id": head.version_id,
        },
    )
