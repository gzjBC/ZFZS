from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.core.config import get_settings
from backend.app.db import base
from backend.app.db.migrate import run_lightweight_migrations
from backend.app.db.session import Base, engine
from backend.app.router import anime, crawlers, health, reminders


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "frontend"


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_lightweight_migrations()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.include_router(health.router, prefix="/api")
    app.include_router(anime.router, prefix="/api")
    app.include_router(reminders.router, prefix="/api")
    app.include_router(crawlers.router, prefix="/api")
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")

    return app


app = create_app()
