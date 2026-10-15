from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ZFZS Anime Assistant"
    app_env: str = "development"
    database_url: str = "sqlite:///./data/zfzs.db"
    bangumi_user_agent: str = "ZFZS/0.2 (https://github.com/gzjBC/ZFZS)"
    xifan_browser_path: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
