import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.db import base
from backend.app.db.migrate import run_lightweight_migrations
from backend.app.db.session import Base, engine


def main() -> None:
    Base.metadata.create_all(bind=engine)
    run_lightweight_migrations()
    print("Database initialized.")


if __name__ == "__main__":
    main()
