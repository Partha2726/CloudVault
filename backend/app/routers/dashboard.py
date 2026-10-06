from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.schemas import DashboardSummary
from app.security import get_current_user
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DashboardSummary:
    return dashboard_service.summary(db, user.id)
