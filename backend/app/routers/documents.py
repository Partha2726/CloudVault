import time
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import AppError
from app.models import User
from app.rate_limit import upload_limit
from app.schemas import (
    AccessLogPage,
    DocumentOut,
    DocumentPage,
    DownloadLinkOut,
    DuplicateOut,
    ProcessingItem,
    ProcessingList,
    S3InfoOut,
    VersionDuplicateOut,
    VersionList,
    VersionOut,
)
from app.security import get_current_user
from app.services import deletion_service, document_service, processing_service, version_service
from app.services.document_service import TYPE_FILTERS, SortKey
from app.services.validation import read_upload, validate_upload
from app.storage import get_storage
from app.storage.base import STORAGE_CLASSES, ObjectStorage

# PostgreSQL `integer` columns: larger page or version numbers are a 422, not a database overflow.
PG_INT_MAX = 2_147_483_647

router = APIRouter(prefix="/documents", tags=["documents"])

TypeFilter = Literal[tuple(TYPE_FILTERS)]  # type: ignore[valid-type]
StorageClassFilter = Literal[STORAGE_CLASSES]  # type: ignore[valid-type]


@router.post(
    "",
    status_code=201,
    response_model=DocumentOut,
    responses={200: {"model": DuplicateOut, "description": "Same name and content already stored"}},
)
@upload_limit
async def upload_document(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> JSONResponse:
    """W2: multipart field `file`, parsed as a stream in memory (doc 05.3, AM-4)."""
    limit = get_settings().max_upload_bytes
    upload = await read_upload(request, limit=limit)
    validated = await run_in_threadpool(validate_upload, upload.filename, upload.data, limit)
    result = await run_in_threadpool(document_service.create_document, db, storage, user, validated)
    if result.duplicate:
        return JSONResponse(status_code=200, content=DuplicateOut(document=result.document).model_dump(mode="json"))
    return JSONResponse(status_code=201, content=result.document.model_dump(mode="json"))


@router.get("", response_model=DocumentPage)
def list_documents(
    q: str | None = Query(None, max_length=200),
    status: Literal["active", "deleted"] = "active",
    type: TypeFilter | None = None,  # noqa: A002  (doc 05.5 parameter name)
    storage_class: StorageClassFilter | None = None,
    sort: SortKey = "-updated",
    page: int = Query(1, ge=1, le=PG_INT_MAX),
    page_size: int = Query(25, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentPage:
    return document_service.list_documents(
        db, user.id, q=q, status=status, type_=type, storage_class=storage_class,
        sort=sort, page=page, page_size=page_size,
    )


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentOut:
    return document_service.get_document(db, user.id, document_id)


@router.get("/{document_id}/download", response_model=DownloadLinkOut)
def download_link(
    document_id: uuid.UUID,
    version: int | None = Query(None, ge=1, le=PG_INT_MAX),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> DownloadLinkOut:
    """W3: a 120 s, version-bound signed link to the simulated store; each call is logged."""
    link = document_service.create_download_link(
        db, user.id, document_id, version, bucket=storage.bucket, now_epoch=int(time.time())
    )
    return DownloadLinkOut(url=link.url, expires_in=link.expires_in)


@router.get("/{document_id}/access-logs", response_model=AccessLogPage)
def access_logs(
    document_id: uuid.UUID,
    page: int = Query(1, ge=1, le=PG_INT_MAX),
    page_size: int = Query(25, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccessLogPage:
    return document_service.list_access_logs(db, user.id, document_id, page, page_size)


@router.delete("/{document_id}", status_code=204)
def soft_delete(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    """W4: move to trash (simulated S3 delete marker). Idempotent."""
    deletion_service.soft_delete(db, storage, user.id, document_id)
    return Response(status_code=204)


@router.post("/{document_id}/undelete", response_model=DocumentOut)
def undelete(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> DocumentOut:
    """Remove the delete marker; a second call returns 409 NOT_DELETED and changes nothing."""
    return deletion_service.undelete(db, storage, user.id, document_id)


@router.delete("/{document_id}/permanent", status_code=204)
def permanent_delete(
    document_id: uuid.UUID,
    confirm: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    """Delete every stored version and marker, then the rows. Requires ?confirm=true."""
    if not confirm:
        raise AppError("VALIDATION_ERROR", 422, "Permanent delete requires confirm=true")
    deletion_service.permanent_delete(db, storage, user.id, document_id)
    return Response(status_code=204)


@router.get("/{document_id}/versions", response_model=VersionList)
def list_versions(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VersionList:
    return version_service.list_versions(db, user.id, document_id)


@router.post(
    "/{document_id}/versions",
    status_code=201,
    response_model=VersionOut,
    responses={200: {"model": VersionDuplicateOut, "description": "Same content as the current version"}},
)
@upload_limit
async def upload_version(
    request: Request,
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> JSONResponse:
    """W5: multipart field `file`; a new version of an ACTIVE document."""
    limit = get_settings().max_upload_bytes
    upload = await read_upload(request, limit=limit)
    validated = await run_in_threadpool(validate_upload, upload.filename, upload.data, limit)
    version = await run_in_threadpool(version_service.upload_version, db, storage, user, document_id, validated)
    if version is None:
        return JSONResponse(status_code=200, content=VersionDuplicateOut().model_dump(mode="json"))
    return JSONResponse(status_code=201, content=version.model_dump(mode="json"))


@router.post("/{document_id}/versions/{version_number}/restore", status_code=201, response_model=VersionOut)
def restore_version(
    document_id: uuid.UUID,
    version_number: int = Path(ge=1, le=PG_INT_MAX),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> VersionOut:
    """W6: copy version n onto the key as a new STANDARD version. Not idempotent."""
    return version_service.restore_version(db, storage, user, document_id, version_number)


@router.get("/{document_id}/s3-info", response_model=S3InfoOut)
def s3_info(
    document_id: uuid.UUID,
    version: int | None = Query(None, ge=1, le=PG_INT_MAX),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> S3InfoOut:
    """W8: simulated HeadObject + tags for the current or a given version (source "simulated-s3")."""
    return version_service.s3_info(db, storage, user.id, document_id, version)


@router.get("/{document_id}/processing", response_model=ProcessingList)
def processing_status(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProcessingList:
    return processing_service.list_jobs(db, user.id, document_id)


@router.post("/{document_id}/processing/retry", status_code=202, response_model=ProcessingItem)
def retry_processing(
    document_id: uuid.UUID,
    version: int | None = Query(None, ge=1, le=PG_INT_MAX),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProcessingItem:
    """W16 (Tier 3): re-queue a FAILED or stalled job; the worker picks it up."""
    return processing_service.retry(db, user.id, document_id, version)
