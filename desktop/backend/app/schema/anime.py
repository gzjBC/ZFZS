from datetime import datetime

from pydantic import BaseModel, Field


class AnimeBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    title_cn: str | None = None
    cover_url: str | None = None
    summary: str | None = None
    status: str = Field(default="watching", pattern=r"^(watching|paused|finished)$")
    broadcast_day: int | None = Field(default=None, ge=0, le=6)
    broadcast_time: str = Field(default="20:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    reminder_enabled: bool = True
    reminder_minutes: int = Field(default=15, ge=0, le=1440)
    watched_episodes: int = Field(default=0, ge=0)
    total_episodes: int | None = Field(default=None, ge=0)
    play_url: str | None = None
    source: str | None = None
    source_id: str | None = None
    source_url: str | None = None
    source_status: str | None = None
    year: int | None = Field(default=None, ge=1900, le=2200)
    score: float | None = Field(default=None, ge=0, le=10)
    user_rating: float | None = Field(default=None, ge=0, le=10, allow_inf_nan=False)
    tags: str | None = None


class AnimeCreate(AnimeBase):
    pass


class AnimeUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    title_cn: str | None = None
    cover_url: str | None = None
    summary: str | None = None
    status: str | None = Field(default=None, pattern=r"^(watching|paused|finished)$")
    broadcast_day: int | None = Field(default=None, ge=0, le=6)
    broadcast_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    reminder_enabled: bool | None = None
    reminder_minutes: int | None = Field(default=None, ge=0, le=1440)
    watched_episodes: int | None = Field(default=None, ge=0)
    total_episodes: int | None = Field(default=None, ge=0)
    play_url: str | None = None
    source: str | None = None
    source_id: str | None = None
    source_url: str | None = None
    source_status: str | None = None
    year: int | None = Field(default=None, ge=1900, le=2200)
    score: float | None = Field(default=None, ge=0, le=10)
    user_rating: float | None = Field(default=None, ge=0, le=10, allow_inf_nan=False)
    tags: str | None = None


class AnimeProgressUpdate(BaseModel):
    watched_episodes: int = Field(ge=0)


class AnimeRead(AnimeBase):
    id: int
    last_reminded_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
