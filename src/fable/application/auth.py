"""Framework-independent username/password authentication and login throttling."""
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import re
import secrets
import sqlite3
import threading
from typing import Protocol
from uuid import uuid4

from fable.domain.user import User
from fable.infrastructure.security import hash_password, verify_password


class AuthStore(Protocol):
    def create_user(self, user: User, password_hash: str) -> None: ...
    def find_by_username(self, username: str) -> tuple[User, str] | None: ...
    def create_session(self, token: str, user_id: str, created_at: datetime,
                       expires_at: datetime) -> None: ...
    def user_for_token(self, token: str, now: datetime) -> User | None: ...
    def delete_session(self, token: str) -> None: ...
    def prune_expired(self, now: datetime) -> None: ...


class AuthError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class AuthService:
    def __init__(self, store: AuthStore, *, session_ttl_days: int = 30,
                 allow_registration: bool = True,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.session_ttl = timedelta(days=session_ttl_days)
        self.allow_registration = allow_registration
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._failures: dict[str, list[datetime]] = {}
        self._lock = threading.Lock()
        # Unknown users still pay for one real scrypt verification per attempt.
        self._dummy_hash = hash_password(secrets.token_urlsafe(32))

    def _session(self, user: User) -> tuple[User, str]:
        now = self.clock()
        self.store.prune_expired(now)
        token = secrets.token_urlsafe(32)
        self.store.create_session(token, user.id, now, now + self.session_ttl)
        return user, token

    def register(self, username: str, password: str) -> tuple[User, str]:
        if not self.allow_registration:
            raise AuthError(403, "Регистрация отключена")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
            raise AuthError(422, "Имя пользователя: от 3 до 32 символов, латинские буквы, цифры, _, . и -")
        if not 8 <= len(password) <= 128:
            raise AuthError(422, "Пароль должен содержать от 8 до 128 символов")
        user = User(uuid4().hex, username, self.clock().isoformat())
        try:
            self.store.create_user(user, hash_password(password))
        except sqlite3.IntegrityError:
            raise AuthError(409, "Имя пользователя уже занято") from None
        return self._session(user)

    def login(self, username: str, password: str) -> tuple[User, str]:
        key = username.lower()
        # Include verification in the critical section: simultaneous failed
        # requests cannot bypass the five-attempt limit.
        with self._lock:
            now = self.clock()
            cutoff = now - timedelta(minutes=5)
            self._failures = {name: recent for name, attempts in self._failures.items()
                              if (recent := [stamp for stamp in attempts if stamp > cutoff])}
            attempts = self._failures.get(key, [])
            if len(attempts) >= 5:
                raise AuthError(429, "Слишком много попыток. Попробуй позже")
            found = self.store.find_by_username(username)
            valid = verify_password(password, found[1] if found else self._dummy_hash)
            if not found or not valid:
                self._failures[key] = [*attempts, now]
                raise AuthError(401, "Неверное имя пользователя или пароль")
            self._failures.pop(key, None)
        return self._session(found[0])

    def logout(self, token: str | None) -> None:
        if token:
            self.store.delete_session(token)

    def current_user(self, token: str | None) -> User:
        user = self.store.user_for_token(token, self.clock()) if token else None
        if user is None:
            raise AuthError(401, "Нужно войти")
        return user
