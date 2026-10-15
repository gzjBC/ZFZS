import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backend.app.core.desktop_runtime import prepare_desktop_storage
from backend.app.core.config import Settings


class DesktopRuntimeTests(unittest.TestCase):
    def test_legacy_data_is_copied_once_without_overwriting_user_data(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            (project / "data").mkdir(parents=True)
            legacy = project / "data/zfzs.db"
            with closing(sqlite3.connect(legacy)) as db:
                db.execute("CREATE TABLE marker (title TEXT)")
                db.execute("INSERT INTO marker VALUES ('original')")
                db.commit()
            target_dir = Path(directory) / "user data"
            with patch.dict(os.environ, {"ZFZS_DATA_DIR": str(target_dir)}, clear=True):
                prepare_desktop_storage(project)
                self.assertTrue(legacy.exists())
                with closing(sqlite3.connect(target_dir / "zfzs.db")) as db:
                    self.assertEqual(db.execute("SELECT title FROM marker").fetchone()[0], "original")
                    db.execute("UPDATE marker SET title = 'user edit'")
                    db.commit()
                del os.environ["DATABASE_URL"]
                prepare_desktop_storage(project)
                with closing(sqlite3.connect(target_dir / "zfzs.db")) as db:
                    self.assertEqual(db.execute("SELECT title FROM marker").fetchone()[0], "user edit")

    def test_explicit_database_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"ZFZS_DATA_DIR": directory, "DATABASE_URL": "sqlite:///:memory:"}):
                prepare_desktop_storage(Path(directory))
                self.assertEqual(os.environ["DATABASE_URL"], "sqlite:///:memory:")
                self.assertFalse((Path(directory) / "zfzs.db").exists())

    def test_env_template_loads_without_unknown_setting_errors(self):
        example = Path(__file__).resolve().parents[1] / ".env.example"
        settings = Settings(_env_file=example)
        self.assertTrue(settings.bangumi_user_agent.startswith("ZFZS/"))
