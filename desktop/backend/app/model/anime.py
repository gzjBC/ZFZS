from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class Anime(Base):
    __tablename__ = "anime"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title_cn: Mapped[str | None] = mapped_column(String(255), default=None)
    cover_url: Mapped[str | None] = mapped_column(Text, default=None)
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(32), default="watching", index=True)

    broadcast_day: Mapped[int | None] = mapped_column(Integer, default=None)
    broadcast_time: Mapped[str] = mapped_column(String(5), default="20:00")
    reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reminder_minutes: Mapped[int] = mapped_column(Integer, default=15)

    watched_episodes: Mapped[int] = mapped_column(Integer, default=0)
    total_episodes: Mapped[int | None] = mapped_column(Integer, default=None)
    play_url: Mapped[str | None] = mapped_column(Text, default=None)

    source: Mapped[str | None] = mapped_column(String(64), default=None)
    source_id: Mapped[str | None] = mapped_column(String(128), default=None, index=True)
    source_url: Mapped[str | None] = mapped_column(Text, default=None)
    source_status: Mapped[str | None] = mapped_column(String(64), default=None)
    year: Mapped[int | None] = mapped_column(Integer, default=None)
    score: Mapped[float | None] = mapped_column(Float, default=None)
    tags: Mapped[str | None] = mapped_column(Text, default=None)

    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
