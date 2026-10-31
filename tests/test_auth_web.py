from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

from fable.presentation.web import create_app
from test_bootstrap import settings
from test_web import EMPTY_SETUP, FakeFactory, events


class AuthWebTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = settings(auth_db_path=self.root / "auth.db", sessions_path=self.root / "games")
        self.app = create_app(self.config, session_factory=FakeFactory())
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def register(self, client=None, username="Alice", password="password123"):
        return (client or self.client).post("/api/auth/register", json={
            "username": username, "password": password,
        })

    def test_registration_cookie_me_and_duplicate_username(self):
        response = self.register()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.json()), {"user"})
        self.assertEqual(set(response.json()["user"]), {"id", "username"})
        self.assertEqual(response.json()["user"]["username"], "Alice")
        cookie = response.headers["set-cookie"]
        for part in ["fable_session=", "HttpOnly", "SameSite=lax", "Path=/", "Max-Age=2592000"]:
            self.assertIn(part, cookie)
        self.assertNotIn("Secure", cookie)
        self.assertEqual(self.client.get("/api/auth/me").json(), response.json())
        duplicate = self.register(username="aLiCe")
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json(), {"detail": "Имя пользователя уже занято"})

    def test_invalid_registration_has_string_detail(self):
        for body in [{}, {"username": None, "password": "password123"},
                     {"username": 123, "password": "password123"},
                     {"username": "ab", "password": "password123"},
                     {"username": "a" * 33, "password": "password123"},
                     {"username": "name space", "password": "password123"},
                     {"username": "Юзер", "password": "password123"},
                     {"username": "Alice", "password": "short"},
                     {"username": "Alice", "password": "p" * 129}]:
            with self.subTest(body=body):
                response = self.client.post("/api/auth/register", json=body)
                self.assertEqual(response.status_code, 422)
                self.assertIsInstance(response.json()["detail"], str)

    def test_login_failures_rate_limit_and_logout(self):
        user = self.register().json()
        old_token = self.client.cookies.get("fable_session")
        assert old_token is not None
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 204)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        with TestClient(self.app) as replay:
            replay.cookies.set("fable_session", old_token)
            self.assertEqual(replay.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 204)
        unknown = self.client.post("/api/auth/login", json={"username": "Nobody", "password": "wrong"})
        self.assertEqual(unknown.json(), {"detail": "Неверное имя пользователя или пароль"})
        for i in range(5):
            response = self.client.post("/api/auth/login", json={"username": "ALICE", "password": "wrong"})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), unknown.json())
        limited = self.client.post("/api/auth/login", json={"username": "alice", "password": "password123"})
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json(), {"detail": "Слишком много попыток. Попробуй позже"})
        # A separate service instance still accepts the valid persistent account.
        with TestClient(create_app(self.config, session_factory=FakeFactory())) as fresh:
            response = fresh.post("/api/auth/login", json={"username": "aLiCe", "password": "password123"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), user)

    def test_games_require_auth_on_every_endpoint(self):
        for method, path, body in [
            ("GET", "/api/games", None), ("POST", "/api/games", EMPTY_SETUP),
            ("GET", "/api/games/missing", None), ("DELETE", "/api/games/missing", None),
            ("POST", "/api/games/missing/start", None),
            ("POST", "/api/games/missing/actions", {"action": "Жду"}),
        ]:
            with self.subTest(method=method, path=path):
                response = self.client.request(method, path, json=body)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json(), {"detail": "Нужно войти"})
        self.client.cookies.set("fable_session", "forged")
        self.assertEqual(self.client.get("/api/games").status_code, 401)

    def test_games_are_scoped_in_cache_on_disk_and_after_restart(self):
        alice = self.register().json()["user"]
        game = self.client.post("/api/games", json=EMPTY_SETUP).json()
        path = f'/api/games/{game["id"]}'
        self.assertTrue((self.config.sessions_path / alice["id"] / f'{game["id"]}.json').is_file())
        self.assertEqual(events(self.client.post(path + "/start"))[-1][0], "done")
        # A legacy CLI/root save is deliberately not assigned to any web account.
        from fable.infrastructure.session_store import JsonSessionStore
        root = JsonSessionStore(self.config.sessions_path)
        record = JsonSessionStore(self.config.sessions_path / alice["id"]).load(game["id"])
        assert record is not None
        root.save("legacy", record)
        self.assertEqual([g["id"] for g in self.client.get("/api/games").json()], [game["id"]])
        for app in [self.app, create_app(self.config, session_factory=FakeFactory())]:
            with TestClient(app) as bob:
                if app is self.app:
                    self.assertEqual(self.register(bob, "Bobby").status_code, 201)
                else:
                    self.assertEqual(bob.post("/api/auth/login", json={
                        "username": "Bobby", "password": "password123",
                    }).status_code, 200)
                self.assertEqual(bob.get("/api/games").json(), [])
                for method, suffix, body in [("GET", "", None), ("DELETE", "", None),
                                              ("POST", "/start", None),
                                              ("POST", "/actions", {"action": "Жду"}),
                                              ("POST", "/actions", {"action": "  "})]:
                    response = bob.request(method, path + suffix, json=body)
                    self.assertEqual(response.status_code, 404)
                self.assertEqual(bob.get("/api/games/legacy").status_code, 404)
        self.assertEqual(self.client.get(path).status_code, 200)

    def test_origin_check_and_credentialed_cors(self):
        for path, body in [("/api/auth/register", {"username": "Alice", "password": "password123"}),
                           ("/api/auth/login", {"username": "Alice", "password": "password123"}),
                           ("/api/auth/logout", None), ("/api/games", EMPTY_SETUP)]:
            self.assertEqual(self.client.post(path, json=body, headers={
                "Origin": "http://attacker.invalid",
            }).status_code, 403)
        response = self.client.post("/api/auth/register", json={
            "username": "Alice", "password": "password123",
        }, headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 201)
        game = self.client.post("/api/games", json=EMPTY_SETUP,
                                headers={"Origin": "http://localhost:5173"})
        self.assertEqual(game.status_code, 201)
        path = f'/api/games/{game.json()["id"]}'
        self.assertEqual(self.client.delete(path, headers={"Origin": "null"}).status_code, 403)
        self.assertEqual(self.client.delete(path, headers={"Origin": "https://testserver"}).status_code, 403)
        self.assertEqual(self.client.delete(path, headers={"Origin": "http://testserver"}).status_code, 204)
        response = self.client.options("/api/games", headers={
            "Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "POST",
        })
        self.assertEqual(response.headers["access-control-allow-origin"], "http://127.0.0.1:5173")
        self.assertEqual(response.headers["access-control-allow-credentials"], "true")

    def test_expired_cookie_is_rejected_and_pruned(self):
        from datetime import datetime, timedelta, timezone
        from fable.infrastructure.auth_store import SqliteAuthStore
        import sqlite3

        user = self.register().json()["user"]
        store = SqliteAuthStore(self.config.auth_db_path)
        now = datetime.now(timezone.utc)
        store.create_session("expired", user["id"], now - timedelta(days=2), now - timedelta(days=1))
        self.client.cookies.clear()
        self.client.cookies.set("fable_session", "expired")
        for path in ["/api/auth/me", "/api/games"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), {"detail": "Нужно войти"})
        with sqlite3.connect(self.config.auth_db_path) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM sessions").fetchone()[0], 1)

    def test_injected_stores_and_identical_game_ids_remain_isolated(self):
        from unittest.mock import patch
        from uuid import UUID
        from fable.infrastructure.auth_store import SqliteAuthStore
        from fable.infrastructure.session_store import JsonSessionStore

        requested = []

        def user_store(user_id):
            requested.append(user_id)
            return JsonSessionStore(self.root / "injected" / user_id)

        app = create_app(self.config, session_factory=FakeFactory(),
                         auth_store=SqliteAuthStore(self.root / "injected.db"),
                         store_factory=user_store)
        with TestClient(app) as alice, TestClient(app) as bob:
            alice_id = self.register(alice).json()["user"]["id"]
            bob_id = self.register(bob, "Bobby").json()["user"]["id"]
            with patch("fable.presentation.web.uuid4", return_value=UUID(int=1)):
                first = alice.post("/api/games", json=EMPTY_SETUP).json()
                second = bob.post("/api/games", json={**EMPTY_SETUP, "world": "Мир Боба"}).json()
            self.assertEqual(first["id"], second["id"])
            path = f'/api/games/{first["id"]}'
            self.assertEqual(alice.get(path).json(), first)
            self.assertEqual(bob.get(path).json(), second)
            self.assertEqual(alice.delete(path).status_code, 204)
            self.assertEqual(bob.get(path).json(), second)
            self.assertEqual(set(requested), {alice_id, bob_id})

    def test_auth_validation_and_public_health_target(self):
        self.assertEqual(self.client.get("/openapi.json").status_code, 200)
        for body in [{}, {"username": "Alice", "password": None}]:
            response = self.client.post("/api/auth/login", json=body)
            self.assertEqual(response.status_code, 422)
            self.assertIsInstance(response.json()["detail"], str)
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            settings(session_ttl_days=0)

    def test_registration_disabled_and_secure_cookie(self):
        config = self.config.model_copy(update={"allow_registration": False})
        with TestClient(create_app(config, session_factory=FakeFactory())) as client:
            response = self.register(client)
            self.assertEqual(response.status_code, 403)
            self.assertIsInstance(response.json()["detail"], str)
        config = self.config.model_copy(update={"cookie_secure": True, "session_ttl_days": 1})
        with TestClient(create_app(config, session_factory=FakeFactory()), base_url="https://testserver") as client:
            response = self.register(client)
            self.assertIn("Secure", response.headers["set-cookie"])
            self.assertIn("Max-Age=86400", response.headers["set-cookie"])
            self.assertEqual(client.get("/api/auth/me").status_code, 200)
