from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.crawlers.xifan_playwright import (
    XIFAN_SEARCH,
    XifanCrawlerError,
    XifanCrawlerOptions,
    XifanPlaywrightCrawler,
)
from backend.app.db.session import get_db
from backend.app.schema.anime import AnimeRead
from backend.app.schema.crawler import XifanAnimeResult, XifanSearchResponse
from backend.app.service.anime_service import import_xifan_result


router = APIRouter(prefix="/crawlers", tags=["crawlers"])


@router.get("/xifan/search", response_model=XifanSearchResponse)
def search_xifan(
    q: str = Query(min_length=1),
    limit: int = Query(default=5, ge=1, le=20),
    headed: bool = Query(default=False),
):
    crawler = XifanPlaywrightCrawler(XifanCrawlerOptions(headed=headed))
    try:
        results = crawler.search(q, limit=limit)
    except XifanCrawlerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return XifanSearchResponse(
        keyword=q,
        source_url=XIFAN_SEARCH.format(keyword=quote(q)),
        results=results,
    )


@router.post("/xifan/import", response_model=AnimeRead)
def import_from_xifan(payload: XifanAnimeResult, db: Session = Depends(get_db)):
    return import_xifan_result(db, payload)
