from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tests.application.test_bootstrap import settings


class RepositoryFactoryTests(unittest.TestCase):
    def test_local_default_and_postgres_selection_without_connections(self):
        from fable.bootstrap import create_repository_factory
        from fable.infrastructure.persistence.game_repository import JsonGameRepository
        from fable.infrastructure.persistence.postgres import PostgresGameRepository
        with TemporaryDirectory() as directory:
            local = create_repository_factory(settings(sessions_path=Path(directory)))
            self.assertIsInstance(local(None), JsonGameRepository)
            pool = object()
            remote = create_repository_factory(settings(database_url='postgresql://unused'), pool=pool)
            repo = remote('owner')
            self.assertIsInstance(repo, PostgresGameRepository)
            self.assertIs(repo.pool, pool)
            self.assertEqual(repo.owner_id, 'owner')
