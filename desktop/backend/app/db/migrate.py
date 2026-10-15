from sqlalchemy import inspect, text

from backend.app.db.session import engine


SQLITE_ANIME_COLUMNS = {
    "source_url": "TEXT",
    "source_status": "VARCHAR(64)",
    "year": "INTEGER",
}


def run_lightweight_migrations() -> None:
    if not engine.url.drivername.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "anime" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("anime")}
    with engine.begin() as conn:
        for column, ddl in SQLITE_ANIME_COLUMNS.items():
            if column not in existing_columns:
                conn.execute(text(f"ALTER TABLE anime ADD COLUMN {column} {ddl}"))
