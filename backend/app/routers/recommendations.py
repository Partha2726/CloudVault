import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.schemas import RecommendationList, RecommendationOut
from app.security import get_current_user
from app.services import recommendation_service
from app.storage import get_storage
from app.storage.base import ObjectStorage

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("", response_model=RecommendationList)
def list_recommendations(
    status: Literal["open", "applied", "dismissed", "stale"] = "open",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecommendationList:
    return recommendation_service.list_recommendations(db, user.id, status)


@router.post("/refresh", response_model=RecommendationList)
def refresh(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> RecommendationList:
    """W10: re-run CloudVault's heuristic over the current versions of active documents."""
    return recommendation_service.refresh(db, user.id)


@router.post("/{recommendation_id}/apply", response_model=RecommendationOut)
def apply(
    recommendation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> RecommendationOut:
    """W11: change the simulated storage class (copy, adopt, remove old version). Already applied: 200."""
    return recommendation_service.apply(db, storage, user.id, recommendation_id)


@router.post("/{recommendation_id}/dismiss", response_model=RecommendationOut)
def dismiss(
    recommendation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecommendationOut:
    return recommendation_service.dismiss(db, user.id, recommendation_id)
