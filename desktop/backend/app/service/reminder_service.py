from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.model.anime import Anime


def list_today_due_anime(db: Session, now: datetime | None = None) -> list[Anime]:
    """Return pending occurrences, including tomorrow's advance reminders.

    Broadcast weekdays use the existing Sunday=0 convention. The due window
    ends at midnight after the broadcast day; missed weeks are not replayed.
    """
    now = now or datetime.now()
    stmt = select(Anime).where(
        Anime.status == "watching",
        Anime.reminder_enabled.is_(True),
        Anime.broadcast_day.between(0, 6),
    )
    items = db.scalars(stmt).all()
    return [item for item in items if _is_due(item, now)]


def mark_reminded(db: Session, anime: Anime, now: datetime | None = None) -> Anime:
    anime.last_reminded_at = now or datetime.now()
    db.commit()
    db.refresh(anime)
    return anime


def _is_due(anime: Anime, now: datetime) -> bool:
    if anime.status != "watching" or not anime.reminder_enabled:
        return False
    if (
        anime.total_episodes is not None
        and anime.total_episodes > 0
        and (anime.watched_episodes or 0) >= anime.total_episodes
    ):
        return False
    if anime.broadcast_day not in range(7):
        return False

    reminder_time = _parse_hhmm(anime.broadcast_time)
    # The public schema allows at most 24 hours' advance notice. Checking today
    # and tomorrow covers midnight and Saturday/Sunday without a weekday SQL
    # filter accidentally excluding the next occurrence.
    lead = min(1440, max(0, anime.reminder_minutes or 0))
    for offset in (0, 1):
        day = now.date() + timedelta(days=offset)
        if (day.weekday() + 1) % 7 != anime.broadcast_day:
            continue
        broadcast_at = datetime.combine(day, reminder_time, tzinfo=now.tzinfo)
        reminder_at = broadcast_at - timedelta(minutes=lead)
        expires_at = datetime.combine(day + timedelta(days=1), time.min, tzinfo=now.tzinfo)
        if not reminder_at <= now < expires_at:
            continue
        last = anime.last_reminded_at
        if last is not None:
            # SQLite timestamps are local wall-clock values, normally naive.
            if last.tzinfo is None and now.tzinfo is not None:
                last = last.replace(tzinfo=now.tzinfo)
            elif last.tzinfo is not None and now.tzinfo is None:
                last = last.astimezone().replace(tzinfo=None)
            # A successful advance notification still belongs to this airing
            # if the user subsequently reduces the advance-minute setting.
            cycle_start = datetime.combine(day - timedelta(days=1), time.min, tzinfo=now.tzinfo)
            if cycle_start <= last < expires_at:
                return False
        return True
    return False


def _parse_hhmm(value: str) -> time:
    try:
        hour_text, minute_text = value.split(":", 1)
        return time(hour=int(hour_text), minute=int(minute_text))
    except (AttributeError, ValueError):
        return time(hour=20, minute=0)
