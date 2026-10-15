from pydantic import BaseModel, Field


class XifanAnimeResult(BaseModel):
    title: str
    source: str = "xifan"
    source_id: str | None = None
    source_url: str | None = None
    cover_url: str | None = None
    summary: str | None = None
    score: float | None = None
    status_text: str | None = None
    year: int | None = None
    watched_episodes: int = 0
    total_episodes: int | None = None
    tags: list[str] = Field(default_factory=list)
    play_url: str | None = None


class XifanSearchResponse(BaseModel):
    keyword: str
    source_url: str
    results: list[XifanAnimeResult]
