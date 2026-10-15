from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.schema.anime import AnimeRead
from backend.app.service.reminder_service import list_today_due_anime


router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.get("/today", response_model=list[AnimeRead])
def today_reminders(db: Session = Depends(get_db)):
    return list_today_due_anime(db)
