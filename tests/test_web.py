import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from fable.application.guardrails import BLOCK_MESSAGE, RuleGuardrail
from fable.application.session import GameSession
from fable.domain.consistency import ConsistencyVerdict
from fable.infrastructure.session_store import JsonSessionStore
from fable.presentation.web import create_app
from test_bootstrap import settings


EMPTY_SETUP = {"world": "", "story": "", "character": dict.fromkeys(
    ["name", "role", "goal", "description", "genre"], "")}


def events(response):
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    result = []
    for frame in response.text.strip().split("\n\n"):
        event, data = frame.split("\n", 1)
        assert event.startswith("event: ") and data.startswith("data: ")
        result.append((event[7:], json.loads(data[6:])))
    return result


class FakeChecker:
    def check(self, context, recent, reply):
        return ConsistencyVerdict(False, ("Проверь сцену",))


class FakeSummarizer:
    def summarize(self, previous_summary, messages):
        return "События сохранены"


class FakeFactory:
    def __init__(self):
        self.fail = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.wait = False

    def __call__(self, config, setup, state, snapshot=None):
        factory = self

        class Agent:
            def stream(self, messages):
                if factory.wait:
                    factory.entered.set()
                    if not factory.release.wait(5):
                        raise RuntimeError("test timeout")
                state.update(location="Башня", add_facts=["Сцена началась"])
                yield "Привет\n"
                if factory.fail:
                    state.update(location="Сломанное состояние")
                    raise RuntimeError("сбой агента")
                yield "мир"

        options = dict(agent=Agent(), history_limit=4, guardrail=RuleGuardrail(),
                       summarizer=FakeSummarizer(), checker=FakeChecker())
        return (GameSession.from_snapshot(snapshot, **options) if snapshot is not None
                else GameSession(**options))


class WebTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root_store = JsonSessionStore(Path(self.directory.name) / "games")
        self.factory = FakeFactory()
        self.config = settings(auth_db_path=Path(self.directory.name) / "auth.db")
        self.app = create_app(self.config, session_factory=self.factory, store=self.root_store)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        response = self.client.post("/api/auth/register", json={
            "username": "Tester", "password": "password123",
        })
        self.assertEqual(response.status_code, 201)
        self.store = self.root_store.for_user(response.json()["user"]["id"])

    def authenticate(self, client):
        response = client.post("/api/auth/login", json={
            "username": "Tester", "password": "password123",
        })
        self.assertEqual(response.status_code, 200)

    def create(self):
        response = self.client.post("/api/games", json=EMPTY_SETUP)
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_frontend_dist_environment_override(self):
        dist = Path(self.directory.name) / "frontend"
        dist.mkdir()
        html = "<!doctype html><html><body>Fable test frontend</body></html>"
        (dist / "index.html").write_text(html, encoding="utf-8")
        with patch.dict(os.environ, {"FABLE_FRONTEND_DIST": str(dist)}):
            with TestClient(create_app(self.config, session_factory=self.factory,
                                       store=self.root_store)) as client:
                self.authenticate(client)
                response = client.get("/")
                self.assertEqual(response.status_code, 200)
                self.assertIn("text/html", response.headers["content-type"])
                self.assertEqual(response.text, html)
                self.assertEqual(client.get("/api/games").json(), [])

    def test_create_defaults_and_immediate_persistence(self):
        game = self.create()
        self.assertEqual(game["setup"]["world"], self.config.default_world)
        self.assertEqual(game["setup"]["character"]["name"], self.config.default_character_name)
        self.assertFalse(game["started"])
        self.assertEqual(game["entries"], [])
        self.assertEqual(game["summary"], "")
        self.assertEqual(game["state"], {"location": "", "inventory": [], "facts": []})
        self.assertIsNotNone(self.store.load(game["id"]))

    def test_blocked_setup(self):
        body = {**EMPTY_SETUP, "world": "sexual minor"}
        response = self.client.post("/api/games", json=body)
        self.assertEqual(response.status_code, 422)
        self.assertIn(BLOCK_MESSAGE, response.json()["detail"])
        self.assertEqual(self.store.list(), [])

    def test_list_get_delete_and_missing_routes(self):
        first, second = self.create(), self.create()
        listed = self.client.get("/api/games").json()
        self.assertEqual([g["id"] for g in listed], [second["id"], first["id"]])
        self.assertEqual(set(listed[0]), {"id", "title", "updated_at", "turns"})
        self.assertEqual(self.client.get(f'/api/games/{first["id"]}').json(), first)
        self.assertEqual(self.client.delete(f'/api/games/{first["id"]}').status_code, 204)
        self.assertIsNone(self.store.load(first["id"]))
        for method, suffix, body in [("get", "", None), ("delete", "", None),
                                      ("post", "/start", None), ("post", "/actions", {"action": "Жду"})]:
            response = self.client.request(method, f'/api/games/{first["id"]}{suffix}', json=body)
            self.assertEqual(response.status_code, 404)

    def test_start_sse_and_conflicts(self):
        game = self.create()
        path = f'/api/games/{game["id"]}'
        self.assertEqual(self.client.post(path + "/actions", json={"action": "Жду"}).status_code, 409)
        response = self.client.post(path + "/start")
        parsed = events(response)
        self.assertEqual(parsed[:2], [("chunk", {"text": "Привет\n"}), ("chunk", {"text": "мир"})])
        self.assertEqual(parsed[-1], ("done", {"consistency": {"consistent": False, "issues": ["Проверь сцену"]},
                                              "state": {"location": "Башня", "inventory": [], "facts": ["Сцена началась"]},
                                              "summary": ""}))
        self.assertIn("Привет", response.text)
        self.assertEqual(self.client.post(path + "/start").status_code, 409)
        self.assertEqual(len(self.client.get(path).json()["entries"]), 1)

    def test_actions_persist_and_restore_with_summary(self):
        game = self.create()
        path = f'/api/games/{game["id"]}'
        created = self.store.load(game["id"])["created_at"]
        self.client.post(path + "/start")
        for action in ["Раз", "Два", "Три"]:
            self.assertEqual(events(self.client.post(path + "/actions", json={"action": action}))[-1][0], "done")
        original = self.client.get(path).json()
        self.assertEqual(original["summary"], "События сохранены")
        self.assertEqual(len(original["entries"]), 7)
        with TestClient(create_app(self.config, session_factory=self.factory, store=self.root_store)) as other:
            self.authenticate(other)
            self.assertEqual(other.get(path).json(), original)
            self.assertEqual(events(other.post(path + "/actions", json={"action": "Ещё"}))[-1][0], "done")
        self.assertEqual(self.store.load(game["id"])["created_at"], created)
        self.assertEqual(self.store.list()[0]["turns"], 4)

    def test_blocked_and_empty_actions_leave_history_unchanged(self):
        game = self.create()
        path = f'/api/games/{game["id"]}'
        self.client.post(path + "/start")
        before = self.client.get(path).json()
        disk = self.store.load(game["id"])
        response = self.client.post(path + "/actions", json={"action": "sexual minor"})
        self.assertEqual(events(response), [("blocked", {"message": BLOCK_MESSAGE})])
        self.assertEqual(self.client.get(path).json(), before)
        self.assertEqual(self.store.load(game["id"]), disk)
        for action in ["", "  "]:
            self.assertIn(self.client.post(path + "/actions", json={"action": action}).status_code, (400, 422))

    def test_agent_error_rolls_back_and_releases_lock(self):
        game = self.create()
        path = f'/api/games/{game["id"]}'
        self.client.post(path + "/start")
        before = self.client.get(path).json()
        disk = self.store.load(game["id"])
        self.factory.fail = True
        with self.assertLogs("fable.presentation.web", "ERROR"):
            parsed = events(self.client.post(path + "/actions", json={"action": "Жду"}))
        self.assertEqual([event for event, _ in parsed], ["chunk", "error"])
        self.assertEqual(self.client.get(path).json(), before)
        self.assertEqual(self.store.load(game["id"]), disk)
        self.factory.fail = False
        self.assertEqual(events(self.client.post(path + "/actions", json={"action": "Ещё"}))[-1][0], "done")

    def test_failed_start_remains_unstarted_and_can_retry(self):
        game = self.create()
        path = f'/api/games/{game["id"]}'
        self.factory.fail = True
        with self.assertLogs("fable.presentation.web", "ERROR"):
            self.assertEqual(events(self.client.post(path + "/start"))[-1][0], "error")
        self.assertEqual(self.client.get(path).json(), game)
        self.factory.fail = False
        self.assertEqual(events(self.client.post(path + "/start"))[-1][0], "done")

    def test_done_without_consistency_checker(self):
        def factory(config, setup, state, snapshot=None):
            class Agent:
                def stream(self, messages):
                    yield "Сцена"
            return GameSession(Agent(), 4)

        with TestClient(create_app(self.config, session_factory=factory, store=self.root_store)) as client:
            self.authenticate(client)
            game = client.post("/api/games", json=EMPTY_SETUP).json()
            done = events(client.post(f'/api/games/{game["id"]}/start'))[-1]
            self.assertIsNone(done[1]["consistency"])
            self.assertNotIn("consistency", client.get(f'/api/games/{game["id"]}').json()["entries"][0])

    def test_busy_game_rejects_parallel_stream_and_delete(self):
        game = self.create()
        path = f'/api/games/{game["id"]}'
        self.factory.wait = True
        responses = []
        worker = threading.Thread(target=lambda: responses.append(self.client.post(path + "/start")))
        worker.start()
        try:
            self.assertTrue(self.factory.entered.wait(3))
            self.assertEqual(self.client.post(path + "/start").status_code, 409)
            self.assertEqual(self.client.delete(path).status_code, 409)
        finally:
            self.factory.release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(events(responses[0])[-1][0], "done")

    def test_disconnect_rolls_back_and_releases_lock(self):
        from starlette.requests import ClientDisconnect

        for fail_at in ["http.response.start", "http.response.body"]:
            with self.subTest(fail_at=fail_at):
                game = self.create()
                path = f'/api/games/{game["id"]}'
                saved = self.store.load(game["id"])

                async def disconnect():
                    async def receive():
                        return {"type": "http.request", "body": b"", "more_body": False}

                    async def send(message):
                        if message["type"] == fail_at:
                            raise OSError("client disconnected")

                    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                             "http_version": "1.1", "method": "POST", "scheme": "http",
                             "path": path + "/start", "raw_path": (path + "/start").encode(),
                             "query_string": b"", "headers": [(b"cookie",
                                 f"fable_session={self.client.cookies.get('fable_session')}".encode())],
                             "server": ("test", 80),
                             "client": ("test", 123)}
                    with self.assertRaises(ClientDisconnect):
                        await self.app(scope, receive, send)

                asyncio.run(disconnect())
                self.assertEqual(self.client.get(path).json(), game)
                self.assertEqual(self.store.load(game["id"]), saved)
                self.assertEqual(events(self.client.post(path + "/start"))[-1][0], "done")

    def test_invalid_body_fields_are_rejected(self):
        for body in [{}, {**EMPTY_SETUP, "world": None}, {**EMPTY_SETUP, "world": 12}]:
            self.assertEqual(self.client.post("/api/games", json=body).status_code, 422)
        game = self.create()
        self.assertEqual(self.client.post(f'/api/games/{game["id"]}/actions',
                                          json={"action": None}).status_code, 422)

    def test_cors_and_settings_validation(self):
        response = self.client.options("/api/games", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")
        with self.assertRaisesRegex(ValueError, "API_KEY"):
            create_app(self.config.model_copy(update={"api_key": ""}), store=self.root_store)
