"""SQLite users and hashed cookie sessions; each call owns its connection."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3

from fable.domain.user import User


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


class SqliteAuthStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE COLLATE NOCASE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
            """)

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _user(row) -> User:
        return User(row["id"], row["username"], row["created_at"])

    def create_user(self, user: User, password_hash: str) -> None:
        with self._connection() as connection:
            connection.execute("INSERT INTO users VALUES (?, ?, ?, ?)",
                               (user.id, user.username, password_hash, user.created_at))

    def find_by_username(self, username: str) -> tuple[User, str] | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return (self._user(row), row["password_hash"]) if row else None

    def get_user(self, user_id: str) -> User | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._user(row) if row else None

    def create_session(self, token: str, user_id: str, created_at: datetime,
                       expires_at: datetime) -> None:
        with self._connection() as connection:
            connection.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)",
                               (_token_hash(token), user_id, _timestamp(created_at), _timestamp(expires_at)))

    def user_for_token(self, token: str, now: datetime) -> User | None:
        with self._connection() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (_timestamp(now),))
            row = connection.execute("""
                SELECT users.* FROM users JOIN sessions ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
            """, (_token_hash(token), _timestamp(now))).fetchone()
        return self._user(row) if row else None

    def delete_session(self, token: str) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))

    def prune_expired(self, now: datetime) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (_timestamp(now),))
