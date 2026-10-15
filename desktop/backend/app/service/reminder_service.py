from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.model.anime import Anime


def list_today_due_anime(db: Session, now: datetime | None = None) -> list[Anime]:
    now = now or datetime.now()
    weekday = (now.weekday() + 1) % 7

    stmt = select(Anime).where(
        Anime.status == "watching",
        Anime.reminder_enabled.is_(True),
        Anime.broadcast_day == weekday,
    )
    items = db.scalars(stmt).all()
    return [item for item in items if _is_due(item, now)]


def mark_reminded(db: Session, anime: Anime, now: datetime | None = None) -> Anime:
    anime.last_reminded_at = now or datetime.now()
    db.commit()
    db.refresh(anime)
    return anime


def _is_due(anime: Anime, now: datetime) -> bool:
    if anime.last_reminded_at and anime.last_reminded_at.date() == now.date():
        return False

    reminder_time = _parse_hhmm(anime.broadcast_time)
    broadcast_at = datetime.combine(now.date(), reminder_time)
    reminder_at = broadcast_at - timedelta(minutes=anime.reminder_minutes)
    return now >= reminder_at


def _parse_hhmm(value: str) -> time:
    try:
        hour_text, minute_text = value.split(":", 1)
        return time(hour=int(hour_text), minute=int(minute_text))
    except (AttributeError, ValueError):
        return time(hour=20, minute=0)
