from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from fable.infrastructure.security import hash_password, verify_password


class AuthStoreTests(unittest.TestCase):
    def test_expiry_compares_instants_across_timezones(self):
        from fable.domain.user import User
        from fable.infrastructure.auth_store import SqliteAuthStore

        with TemporaryDirectory() as directory:
            store = SqliteAuthStore(Path(directory) / "auth.db")
            now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
            store.create_user(User("alice", "Alice", now.isoformat()), "hash")
            expiry = now.astimezone(timezone(timedelta(hours=-4)))
            store.create_session("expired", "alice", now - timedelta(days=1), expiry)
            user = store.get_user("alice")
            self.assertEqual(store.user_for_token("expired", now - timedelta(seconds=1)), user)
            self.assertIsNone(store.user_for_token("expired", now))

    def test_store_users_sessions_and_expiry(self):
        from fable.domain.user import User
        from fable.infrastructure.auth_store import SqliteAuthStore

        with TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "auth.db"
            store = SqliteAuthStore(path)
            now = datetime.now(timezone.utc)
            user = User("user1", "Alice", now.isoformat())
            store.create_user(user, "password-hash")
            self.assertEqual(store.get_user(user.id), user)
            self.assertIsNone(store.get_user("missing"))
            self.assertEqual(store.find_by_username("aLiCe"), (user, "password-hash"))
            self.assertIsNone(store.find_by_username("missing"))
            with self.assertRaises(sqlite3.IntegrityError):
                store.create_user(User("user2", "ALICE", now.isoformat()), "hash")
            store.create_session("secret-token", user.id, now, now + timedelta(days=1))
            self.assertEqual(store.user_for_token("secret-token", now), user)
            self.assertIsNone(store.user_for_token("missing", now))
            # A new instance can restore sessions; plaintext tokens never reach disk.
            self.assertEqual(SqliteAuthStore(path).user_for_token("secret-token", now), user)
            with sqlite3.connect(path) as connection:
                self.assertNotEqual(connection.execute("SELECT token_hash FROM sessions").fetchone()[0],
                                    "secret-token")
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            store.delete_session("secret-token")
            self.assertIsNone(store.user_for_token("secret-token", now))
            store.create_session("expired", user.id, now - timedelta(days=2), now)
            self.assertIsNone(store.user_for_token("expired", now))
            store.prune_expired(now)
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM sessions").fetchone()[0], 0)


class AuthServiceTests(unittest.TestCase):
    def setUp(self):
        from fable.application.auth import AuthService
        from fable.infrastructure.auth_store import SqliteAuthStore

        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.store = SqliteAuthStore(Path(self.directory.name) / "auth.db")
        self.auth = AuthService(self.store, clock=lambda: self.now)

    def test_register_login_logout_and_expiry(self):
        from fable.application.auth import AuthError

        user, token = self.auth.register("Alice", "password123")
        self.assertEqual(self.auth.current_user(token), user)
        other, other_token = self.auth.login("ALICE", "password123")
        self.assertEqual(other, user)
        self.assertNotEqual(other_token, token)
        self.auth.logout(token)
        with self.assertRaises(AuthError) as error:
            self.auth.current_user(token)
        self.assertEqual(error.exception.status_code, 401)
        self.now += timedelta(days=30)
        with self.assertRaises(AuthError):
            self.auth.current_user(other_token)

    def test_rate_limit_has_case_insensitive_key_and_expires(self):
        from fable.application.auth import AuthError

        self.auth.register("Alice", "password123")
        for i in range(5):
            with self.assertRaises(AuthError) as error:
                self.auth.login("ALICE" if i % 2 else "alice", "wrongpassword")
            self.assertEqual(error.exception.status_code, 401)
        with self.assertRaises(AuthError) as error:
            self.auth.login("Alice", "password123")
        self.assertEqual(error.exception.status_code, 429)
        self.now += timedelta(minutes=5)
        self.assertEqual(self.auth.login("Alice", "password123")[0].username, "Alice")

    def test_parallel_failures_cannot_bypass_rate_limit(self):
        from concurrent.futures import ThreadPoolExecutor
        from fable.application.auth import AuthError

        def attempt(index):
            try:
                self.auth.login("Unknown", "wrongpassword")
            except AuthError as error:
                return error.status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(attempt, range(8)))
        self.assertEqual(statuses.count(401), 5)
        self.assertEqual(statuses.count(429), 3)

    def test_user_game_namespaces_validate_ids_and_reject_symlinks(self):
        from fable.infrastructure.session_store import JsonSessionStore

        root = JsonSessionStore(Path(self.directory.name) / "games")
        for value in ["", "../escape", "a/b", "/absolute"]:
            with self.assertRaises(ValueError):
                root.for_user(value)
        (Path(self.directory.name) / "games" / "linked").symlink_to(self.directory.name)
        with self.assertRaises(ValueError):
            root.for_user("linked")

    def test_unknown_user_runs_password_verification(self):
        from fable.application.auth import AuthError
        from unittest.mock import patch

        with patch("fable.application.auth.verify_password", wraps=verify_password) as verify:
            with self.assertRaises(AuthError) as error:
                self.auth.login("unknown", "password123")
        self.assertEqual(error.exception.status_code, 401)
        verify.assert_called_once()


class PasswordTests(unittest.TestCase):
    def test_password_hash_and_verification(self):
        encoded = hash_password("пароль123")
        self.assertTrue(encoded.startswith("scrypt$16384$8$1$"))
        self.assertTrue(verify_password("пароль123", encoded))
        self.assertFalse(verify_password("wrong", encoded))
        self.assertNotEqual(hash_password("пароль123"), encoded)
        for invalid in ["", "scrypt$bad", "scrypt$16384$8$1$@$@",
                        encoded.replace("16384", "999999999")]:
            self.assertFalse(verify_password("пароль123", invalid))
