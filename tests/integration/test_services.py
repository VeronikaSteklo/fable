"""Opt-in real-service checks; never connect without explicit test URLs."""
from datetime import datetime, timedelta, timezone
import os
import sqlite3
import time
import unittest
from uuid import uuid4


@unittest.skipUnless(os.getenv('FABLE_TEST_DATABASE_URL'), 'FABLE_TEST_DATABASE_URL not set')
class PostgresTests(unittest.TestCase):
    def setUp(self):
        from psycopg_pool import ConnectionPool
        from fable.infrastructure.persistence.postgres import migrate, PostgresAuthStore
        from fable.domain.users.user import User
        self.pool = ConnectionPool(os.environ['FABLE_TEST_DATABASE_URL'], min_size=1, max_size=2, open=True)
        self.addCleanup(self.pool.close)
        migrate(self.pool)
        self.auth = PostgresAuthStore(self.pool)
        self.now = datetime.now(timezone.utc)
        self.user = User(uuid4().hex, 'u' + uuid4().hex[:20], self.now.isoformat())
        self.auth.create_user(self.user, 'hash')
        self.addCleanup(self.cleanup_user)

    def cleanup_user(self):
        with self.pool.connection() as conn:
            conn.execute('DELETE FROM games WHERE owner_id = %s', (self.user.id,))
            conn.execute('DELETE FROM users WHERE id = %s', (self.user.id,))

    def test_migrations_idempotent(self):
        from fable.infrastructure.persistence.postgres import migrate
        migrate(self.pool)
        migrate(self.pool)
        with self.pool.connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM schema_migrations').fetchone()[0], 1)

    def test_migration_command_without_llm_settings(self):
        import subprocess
        import sys
        env = {**os.environ, 'DATABASE_URL': os.environ['FABLE_TEST_DATABASE_URL']}
        for name in ('API_KEY', 'BASE_URL', 'MODEL'):
            env.pop(name, None)
        result = subprocess.run([sys.executable, '-m', 'fable.infrastructure.persistence.postgres.cli'],
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Миграции PostgreSQL применены', result.stdout)

    def test_auth_crud_expiry_and_case_uniqueness(self):
        from fable.domain.users.user import User
        self.assertEqual(self.auth.get_user(self.user.id), self.user)
        self.assertEqual(self.auth.find_by_username(self.user.username.upper()), (self.user, 'hash'))
        with self.assertRaises(sqlite3.IntegrityError):
            self.auth.create_user(User(uuid4().hex, self.user.username.upper(), self.user.created_at), 'hash')
        token = uuid4().hex
        self.auth.create_session(token, self.user.id, self.now, self.now + timedelta(seconds=1))
        self.assertEqual(self.auth.user_for_token(token, self.now), self.user)
        with self.pool.connection() as conn:
            row = conn.execute('SELECT token_hash FROM auth_sessions WHERE user_id=%s', (self.user.id,)).fetchone()
            self.assertNotEqual(row[0], token)
        self.auth.delete_session(token)
        self.assertIsNone(self.auth.user_for_token(token, self.now))
        self.auth.create_session(token, self.user.id, self.now, self.now)
        self.auth.prune_expired(self.now)
        self.assertIsNone(self.auth.user_for_token(token, self.now))

    def test_game_roundtrip_scope_and_conflict(self):
        from fable.infrastructure.persistence.postgres import PostgresGameRepository
        from fable.application.ports import StoredGame, PersistenceConflict
        from fable.domain.game.game import Game
        from fable.bootstrap import apply_setup_defaults
        from fable.domain.game.setup import GameSetup
        from tests.application.test_bootstrap import settings
        from tests.presentation.web.test_web import EMPTY_SETUP, FakeFactory
        setup = apply_setup_defaults(GameSetup.from_dict(EMPTY_SETUP), settings())
        game = Game.create(uuid4().hex, self.user.id, setup, self.now.isoformat())
        session = FakeFactory()(settings(), setup, game.state).to_snapshot()
        repo = PostgresGameRepository(self.pool, self.user.id)
        repo.add(StoredGame(game, session))
        first, stale = repo.get(game.id), repo.get(game.id)
        self.assertEqual(first.session, session)
        self.assertEqual(first.game.setup, setup)
        self.assertEqual(repo.list_summaries()[0]['character_name'], setup.character.name)
        hidden = PostgresGameRepository(self.pool, 'not-owner')
        self.assertIsNone(hidden.get(game.id))
        self.assertEqual(hidden.list_summaries(), [])
        hidden.delete(game.id)
        repo.save(first)
        with self.assertRaises(PersistenceConflict):
            repo.save(stale)
        with self.assertRaises(ValueError):
            hidden.save(first)
        repo.delete(game.id)
        self.assertIsNone(repo.get(game.id))
        game.id, game.owner_id, game.version = uuid4().hex, None, 0
        legacy = PostgresGameRepository(self.pool, None)
        legacy.add(StoredGame(game, session))
        try:
            self.assertIsNotNone(legacy.get(game.id))
            self.assertIsNone(repo.get(game.id))
        finally:
            legacy.delete(game.id)


@unittest.skipUnless(os.getenv('FABLE_TEST_REDIS_URL'), 'FABLE_TEST_REDIS_URL not set')
class RedisTests(unittest.TestCase):
    def setUp(self):
        from redis import Redis
        self.client = Redis.from_url(os.environ['FABLE_TEST_REDIS_URL'])
        self.addCleanup(self.client.close)
        self.key = uuid4().hex

    def test_exclusivity_owner_release_and_ttl(self):
        from fable.infrastructure.coordination import RedisLockManager
        from fable.application.ports import LockHandle
        a, b = RedisLockManager(self.client), RedisLockManager(self.client)
        handle = a.try_acquire(self.key, .15)
        self.assertIsNotNone(handle)
        self.assertIsNone(b.try_acquire(self.key, 1))
        b.release(LockHandle(handle.key, 'wrong'))
        self.assertIsNone(b.try_acquire(self.key, 1))
        time.sleep(.2)
        second = b.try_acquire(self.key, 1)
        self.assertIsNotNone(second)
        a.release(handle)
        self.assertIsNone(a.try_acquire(self.key, 1))
        b.release(second)
        third = a.try_acquire(self.key, 1)
        self.assertIsNotNone(third)
        a.release(third)

    def test_shared_rate_limit_and_expiry(self):
        from fable.infrastructure.coordination import RedisLoginRateLimiter
        a, b = (RedisLoginRateLimiter(self.client, window_seconds=1) for _ in range(2))
        for _ in range(5):
            self.assertTrue(a.try_attempt(self.key))
        self.assertFalse(b.try_attempt(self.key.upper()))
        time.sleep(1.1)
        self.assertTrue(b.try_attempt(self.key))
        b.reset(self.key)


@unittest.skipUnless(os.getenv('FABLE_TEST_DATABASE_URL') and os.getenv('FABLE_TEST_REDIS_URL'),
                     'Both service URLs required')
class WebIntegrationTests(unittest.TestCase):
    def test_register_create_start_and_get_across_workers(self):
        from fastapi.testclient import TestClient
        from fable.presentation.web.app import create_app
        from tests.application.test_bootstrap import settings
        from tests.presentation.web.test_web import FakeFactory, EMPTY_SETUP, events
        from pathlib import Path
        from tempfile import TemporaryDirectory
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = settings(database_url=os.environ['FABLE_TEST_DATABASE_URL'],
                          redis_url=os.environ['FABLE_TEST_REDIS_URL'],
                          sessions_path=Path(directory.name) / 'sessions',
                          auth_db_path=Path(directory.name) / 'auth.db')
        factory = FakeFactory()
        with TestClient(create_app(config, session_factory=factory)) as a, \
                TestClient(create_app(config, session_factory=FakeFactory())) as b:
            response = a.post('/api/auth/register', json={'username': 'u' + uuid4().hex[:20],
                                                        'password': 'password123'})
            self.assertEqual(response.status_code, 201)
            b.cookies.update(a.cookies)
            created = a.post('/api/games', json=EMPTY_SETUP)
            self.assertEqual(created.status_code, 201)
            path = '/api/games/' + created.json()['id']
            self.assertFalse(b.get(path).json()['started'])
            from concurrent.futures import ThreadPoolExecutor
            factory.wait = True
            with ThreadPoolExecutor(max_workers=1) as executor:
                running = executor.submit(a.post, path + '/start')
                try:
                    self.assertTrue(factory.entered.wait(3))
                    self.assertEqual(b.post(path + '/start').status_code, 409)
                    self.assertEqual(b.delete(path).status_code, 409)
                finally:
                    factory.release.set()
                self.assertEqual(events(running.result(timeout=5))[-1][0], 'done')
            factory.wait = False
            self.assertTrue(b.get(path).json()['started'])
            self.assertEqual(events(b.post(path + '/actions', json={'action': 'Жду'}))[-1][0], 'done')
            self.assertEqual(len(a.get(path).json()['entries']), 3)
            self.assertEqual(a.delete(path).status_code, 204)
            self.assertEqual(b.get(path).status_code, 404)
            user_id = response.json()['user']['id']
        from psycopg import connect
        with connect(os.environ['FABLE_TEST_DATABASE_URL']) as conn:
            conn.execute('DELETE FROM users WHERE id = %s', (user_id,))
