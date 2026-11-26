"""Process-local defaults and opt-in Redis coordination (no silent fallback)."""
from datetime import datetime, timedelta, timezone
import hashlib
import threading
import time
from uuid import uuid4

from fable.application.ports import LockHandle


class InMemoryLockManager:
    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._held = {}

    def try_acquire(self, key: str, ttl: float) -> LockHandle | None:
        with self._lock:
            now = self._clock()
            self._held = {k: v for k, v in self._held.items() if v[1] > now}
            if key in self._held:
                return None
            handle = LockHandle(key, uuid4().hex)
            self._held[key] = (handle.token, now + ttl)
            return handle

    def release(self, handle: LockHandle) -> None:
        with self._lock:
            if self._held.get(handle.key, (None,))[0] == handle.token:
                self._held.pop(handle.key, None)


class InMemoryLoginRateLimiter:
    def __init__(self, *, clock=None):
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._attempts = {}

    def try_attempt(self, key: str) -> bool:
        with self._lock:
            cutoff = self._clock() - timedelta(minutes=5)
            self._attempts = {k: recent for k, stamps in self._attempts.items()
                              if (recent := [s for s in stamps if s > cutoff])}
            attempts = self._attempts.setdefault(key.lower(), [])
            if len(attempts) >= 5:
                return False
            attempts.append(self._clock())
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key.lower(), None)


class RedisLockManager:
    def __init__(self, client):
        self.client = client

    def try_acquire(self, key: str, ttl: float) -> LockHandle | None:
        handle = LockHandle('fable:lock:' + key, uuid4().hex)
        return handle if self.client.set(handle.key, handle.token, nx=True, px=max(1, int(ttl * 1000))) else None

    def release(self, handle: LockHandle) -> None:
        self.client.eval("""
            if redis.call('GET', KEYS[1]) == ARGV[1] then
                return redis.call('DEL', KEYS[1])
            end
            return 0
        """, 1, handle.key, handle.token)


class RedisLoginRateLimiter:
    def __init__(self, client, *, window_seconds=300):
        self.client = client
        self.window_seconds = window_seconds

    @staticmethod
    def _key(key):
        return 'fable:login:' + hashlib.sha256(key.lower().encode()).hexdigest()

    def try_attempt(self, key: str) -> bool:
        # INCR and initial EXPIRE are atomic, including worker crashes.
        count = self.client.eval("""
            local count = redis.call('INCR', KEYS[1])
            if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
            return count
        """, 1, self._key(key), self.window_seconds)
        return count <= 5

    def reset(self, key: str) -> None:
        self.client.delete(self._key(key))
