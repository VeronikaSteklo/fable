from datetime import datetime, timedelta, timezone
import unittest


class CoordinationTests(unittest.TestCase):
    def test_memory_lock_token_and_expiry(self):
        from fable.infrastructure.coordination import InMemoryLockManager
        now = [0.0]
        locks = InMemoryLockManager(clock=lambda: now[0])
        first = locks.try_acquire('game', 10)
        self.assertIsNotNone(first)
        self.assertIsNone(locks.try_acquire('game', 10))
        now[0] = 11
        second = locks.try_acquire('game', 10)
        locks.release(first)
        self.assertIsNone(locks.try_acquire('game', 10))
        locks.release(second)
        self.assertIsNotNone(locks.try_acquire('game', 10))

    def test_memory_limiter_window_and_reset(self):
        from fable.infrastructure.coordination import InMemoryLoginRateLimiter
        now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        limiter = InMemoryLoginRateLimiter(clock=lambda: now[0])
        for _ in range(5):
            self.assertTrue(limiter.try_attempt('Alice'))
        self.assertFalse(limiter.try_attempt('ALICE'))
        now[0] += timedelta(minutes=5)
        self.assertTrue(limiter.try_attempt('alice'))
        limiter.reset('Alice')
        for _ in range(5):
            self.assertTrue(limiter.try_attempt('alice'))
