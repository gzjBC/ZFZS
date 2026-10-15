from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.model.anime import Anime
from backend.app.schema.anime import AnimeCreate, AnimeUpdate
from backend.app.schema.crawler import XifanAnimeResult


def list_anime(db: Session, status: str | None = None) -> list[Anime]:
    stmt = select(Anime).order_by(Anime.broadcast_day, Anime.broadcast_time, Anime.updated_at.desc())
    if status:
        stmt = stmt.where(Anime.status == status)
    return list(db.scalars(stmt).all())


def get_anime(db: Session, anime_id: int) -> Anime | None:
    return db.get(Anime, anime_id)


def create_anime(db: Session, payload: AnimeCreate) -> Anime:
    anime = Anime(**payload.model_dump())
    _sync_completion_state(anime)
    db.add(anime)
    db.commit()
    db.refresh(anime)
    return anime


def update_anime(db: Session, anime: Anime, payload: AnimeUpdate) -> Anime:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(anime, key, value)

    _sync_completion_state(anime)

    db.commit()
    db.refresh(anime)
    return anime


def update_progress(db: Session, anime: Anime, watched_episodes: int) -> Anime:
    anime.watched_episodes = watched_episodes
    if anime.total_episodes is not None and watched_episodes >= anime.total_episodes:
        anime.status = "finished"
    elif anime.status == "finished":
        anime.status = "watching"
    _sync_completion_state(anime)
    db.commit()
    db.refresh(anime)
    return anime


def delete_anime(db: Session, anime: Anime) -> None:
    db.delete(anime)
    db.commit()


def import_search_result(db: Session, payload: XifanAnimeResult) -> Anime:
    existing = None
    if payload.source_id:
        existing = db.scalar(
            select(Anime).where(Anime.source == payload.source, Anime.source_id == payload.source_id)
        )

    tags = ",".join(payload.tags) if payload.tags else None
    values = {
        "title": payload.title,
        "cover_url": payload.cover_url,
        "summary": payload.summary,
        "total_episodes": payload.total_episodes,
        "play_url": payload.play_url or payload.source_url,
        "source": payload.source,
        "source_id": payload.source_id,
        "source_url": payload.source_url,
        "source_status": payload.status_text,
        "year": payload.year,
        "score": payload.score,
        "tags": tags,
    }

    if existing:
        for key, value in values.items():
            setattr(existing, key, value)
        db.commit()
        db.refresh(existing)
        return existing

    anime = Anime(**values)
    anime.status = "watching"
    anime.watched_episodes = payload.watched_episodes
    db.add(anime)
    db.commit()
    db.refresh(anime)
    return anime


def import_xifan_result(db: Session, payload: XifanAnimeResult) -> Anime:
    """Backward-compatible alias for the original API route."""
    return import_search_result(db, payload)


def _sync_completion_state(anime: Anime) -> None:
    if anime.status == "finished":
        if anime.completed_at is None:
            anime.completed_at = datetime.now()
    else:
        anime.completed_at = None
