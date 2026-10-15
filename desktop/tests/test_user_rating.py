import unittest
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from backend.app.db.session import Base
from backend.app.db import migrate
from backend.app.schema.anime import AnimeCreate, AnimeUpdate
from backend.app.schema.crawler import XifanAnimeResult
from backend.app.service import anime_service


class UserRatingTests(unittest.TestCase):
    def test_invalid_user_ratings_are_rejected(self):
        for value in (-1, 11, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                AnimeCreate(title='rated show', user_rating=value)
        self.assertEqual(AnimeCreate(title='rated show', user_rating=0).user_rating, 0)

    def test_personal_rating_survives_metadata_reimport_and_can_be_cleared(self):
        engine = create_engine('sqlite:///:memory:')
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as db:
            anime = anime_service.import_search_result(db, XifanAnimeResult(
                title='rated show', source='bangumi', source_id='42', score=7.0,
            ))
            anime_service.update_anime(db, anime, AnimeUpdate(user_rating=9.5))
            updated = anime_service.import_search_result(db, XifanAnimeResult(
                title='updated title', source='bangumi', source_id='42', score=8.1,
            ))
            self.assertEqual(updated.user_rating, 9.5)
            self.assertEqual(updated.score, 8.1)
            anime_service.update_anime(db, updated, AnimeUpdate(user_rating=None))
            self.assertIsNone(updated.user_rating)
            self.assertEqual(updated.score, 8.1)

    def test_old_database_migration_is_additive_and_idempotent(self):
        engine = create_engine('sqlite:///:memory:')
        self.addCleanup(engine.dispose)
        with engine.begin() as conn:
            conn.execute(text('CREATE TABLE anime (id INTEGER PRIMARY KEY, title TEXT, watched_episodes INTEGER, score FLOAT)'))
            conn.execute(text("INSERT INTO anime VALUES (1, 'existing show', 6, 8.2)"))
        with patch.object(migrate, 'engine', engine):
            migrate.run_lightweight_migrations()
            migrate.run_lightweight_migrations()
        self.assertIn('user_rating', {column['name'] for column in inspect(engine).get_columns('anime')})
        with engine.connect() as conn:
            row = conn.execute(text('SELECT title, watched_episodes, score, user_rating FROM anime')).one()
            self.assertEqual(tuple(row), ('existing show', 6, 8.2, None))
