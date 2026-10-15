from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.schema.anime import AnimeCreate, AnimeProgressUpdate, AnimeRead, AnimeUpdate
from backend.app.service import anime_service, reminder_service


router = APIRouter(prefix="/anime", tags=["anime"])


@router.get("", response_model=list[AnimeRead])
def list_anime(
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
):
    return anime_service.list_anime(db, status=status_filter)


@router.post("", response_model=AnimeRead, status_code=status.HTTP_201_CREATED)
def create_anime(payload: AnimeCreate, db: Session = Depends(get_db)):
    return anime_service.create_anime(db, payload)


@router.get("/{anime_id}", response_model=AnimeRead)
def get_anime(anime_id: int, db: Session = Depends(get_db)):
    anime = anime_service.get_anime(db, anime_id)
    if anime is None:
        raise HTTPException(status_code=404, detail="Anime not found")
    return anime


@router.patch("/{anime_id}", response_model=AnimeRead)
def update_anime(anime_id: int, payload: AnimeUpdate, db: Session = Depends(get_db)):
    anime = anime_service.get_anime(db, anime_id)
    if anime is None:
        raise HTTPException(status_code=404, detail="Anime not found")
    return anime_service.update_anime(db, anime, payload)


@router.delete("/{anime_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_anime(anime_id: int, db: Session = Depends(get_db)):
    anime = anime_service.get_anime(db, anime_id)
    if anime is None:
        raise HTTPException(status_code=404, detail="Anime not found")
    anime_service.delete_anime(db, anime)


@router.post("/{anime_id}/progress", response_model=AnimeRead)
def update_progress(anime_id: int, payload: AnimeProgressUpdate, db: Session = Depends(get_db)):
    anime = anime_service.get_anime(db, anime_id)
    if anime is None:
        raise HTTPException(status_code=404, detail="Anime not found")
    if anime.total_episodes is not None and payload.watched_episodes > anime.total_episodes:
        raise HTTPException(status_code=422, detail="观看进度不能超过总集数")
    return anime_service.update_progress(db, anime, payload.watched_episodes)


@router.post("/{anime_id}/reminded", response_model=AnimeRead)
def mark_reminded(anime_id: int, db: Session = Depends(get_db)):
    anime = anime_service.get_anime(db, anime_id)
    if anime is None:
        raise HTTPException(status_code=404, detail="Anime not found")
    return reminder_service.mark_reminded(db, anime)
