from fastapi import APIRouter

from backend.app.core.config import get_settings


router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    settings = get_settings()
    return {
        "ok": True,
        "app": settings.app_name,
        "env": settings.app_env,
    }
