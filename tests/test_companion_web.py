import unittest

from fastapi.testclient import TestClient

from fable.application.guardrails import BLOCK_MESSAGE
from fable.presentation.web import create_app
from test_web import EMPTY_SETUP, events
import test_web


PROFILE = {"name": "Лис", "role": "Разведчик", "personality": "Осторожный"}
INITIAL_STATE = {"name": "Лис", "role": "Разведчик", "attitude": 0,
                 "attitude_label": "нейтрально", "present": True, "notes": []}


class CompanionWebTests(unittest.TestCase):
    setUp = test_web.WebTests.setUp
    authenticate = test_web.WebTests.authenticate

    def create(self):
        response = self.client.post("/api/games", json={**EMPTY_SETUP, "companions": [PROFILE]})
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_create_get_done_and_persisted_state_have_same_contract(self):
        game = self.create()
        path = f'/api/games/{game["id"]}'
        self.assertEqual(game["setup"]["companions"], [PROFILE])
        self.assertEqual(game["state"]["companions"], [INITIAL_STATE])
        self.assertEqual(game["state"]["location"], "")
        self.assertEqual(self.client.get(path).json(), game)
        done = events(self.client.post(path + "/start"))[-1]
        self.assertEqual(done[0], "done")
        self.assertEqual(done[1]["state"]["companions"], [INITIAL_STATE])
        record = self.store.load(game["id"])
        self.assertEqual(record["state"]["companions"], [INITIAL_STATE])
        with TestClient(create_app(self.config, session_factory=self.factory, store=self.root_store)) as other:
            self.authenticate(other)
            self.assertEqual(other.get(path).json()["state"]["companions"], [INITIAL_STATE])

    def test_invalid_companions_return_string_detail(self):
        for companions in [[{**PROFILE, "name": " "}], [{**PROFILE, "name": "x" * 41}],
                           [{**PROFILE, "role": "x" * 81}], [{**PROFILE, "personality": "x" * 1001}],
                           [PROFILE, {**PROFILE, "name": "лИС"}], [PROFILE] * 4,
                           [{**PROFILE, "name": self.config.default_character_name}],
                           [{**PROFILE, "name": 1}], [{"name": "Лис"}], None, "Лис"]:
            with self.subTest(companions=companions):
                response = self.client.post("/api/games", json={**EMPTY_SETUP, "companions": companions})
                self.assertEqual(response.status_code, 422)
                self.assertIsInstance(response.json()["detail"], str)
        self.assertEqual(self.store.list(), [])

    def test_guardrail_checks_all_companion_fields(self):
        for field in PROFILE:
            response = self.client.post("/api/games", json={**EMPTY_SETUP, "companions": [
                {**PROFILE, field: "sexual minor"},
            ]})
            self.assertEqual(response.status_code, 422)
            self.assertIn(BLOCK_MESSAGE, response.json()["detail"])

    def test_old_records_load_with_empty_companions_or_initialize_profiles(self):
        for keep_profile in [True, False]:
            game = self.create()
            record = self.store.load(game["id"])
            record["state"].pop("companions", None)
            if not keep_profile:
                record["setup"].pop("companions", None)
            self.store.save(game["id"], record)
            with TestClient(create_app(self.config, session_factory=self.factory, store=self.root_store)) as other:
                self.authenticate(other)
                restored = other.get(f'/api/games/{game["id"]}').json()
                self.assertEqual(restored["setup"]["companions"], [PROFILE] if keep_profile else [])
                self.assertEqual(restored["state"]["companions"], [INITIAL_STATE] if keep_profile else [])

    def test_done_contains_confirmed_relationship_changes(self):
        def factory(config, setup, state, snapshot=None):
            session = self.factory(config, setup, state, snapshot)
            inner = session._agent

            class Agent:
                def stream(self, messages):
                    companion = state.companion("Лис")
                    companion.change_attitude(20)
                    companion.remember("Мира помогла Лису")
                    companion.set_present(False)
                    yield from inner.stream(messages)

            session._agent = Agent()
            return session

        with TestClient(create_app(self.config, session_factory=factory, store=self.root_store)) as other:
            self.authenticate(other)
            response = other.post("/api/games", json={**EMPTY_SETUP, "companions": [PROFILE]})
            self.assertEqual(response.status_code, 201)
            path = f'/api/games/{response.json()["id"]}'
            done = events(other.post(path + "/start"))[-1]
            expected = [{**INITIAL_STATE, "attitude": 20, "attitude_label": "дружелюбно",
                         "present": False, "notes": ["Мира помогла Лису"]}]
            self.assertEqual(done[0], "done")
            self.assertEqual(done[1]["state"]["companions"], expected)
            companion_events = [event for event in done[1]["events"] if "companion" in event]
            self.assertEqual([event["type"] for event in companion_events],
                             ["companion_attitude_changed", "companion_learned", "companion_left"])
            self.assertTrue(all(event["companion"] == "Лис" and event["text"] for event in companion_events))
            self.assertEqual(companion_events[0]["delta"], 20)
            self.assertEqual(companion_events[0]["value"], 20)
            restored = other.get(path).json()
            self.assertEqual(restored["state"]["companions"], expected)
            self.assertEqual(restored["entries"][-1]["events"], done[1]["events"])
        with TestClient(create_app(self.config, session_factory=self.factory, store=self.root_store)) as other:
            self.authenticate(other)
            self.assertEqual(other.get(path).json()["state"]["companions"], expected)

    def test_failed_turn_rolls_back_companion_changes(self):
        original = self.factory

        def factory(config, setup, state, snapshot=None):
            session = original(config, setup, state, snapshot)
            inner = session._agent

            class MutatingAgent:
                def stream(self, messages):
                    companion = state.companion("Лис")
                    companion.change_attitude(20)
                    companion.remember("Секрет")
                    companion.set_present(False)
                    yield from inner.stream(messages)

            session._agent = MutatingAgent()
            return session

        with TestClient(create_app(self.config, session_factory=factory, store=self.root_store)) as other:
            self.authenticate(other)
            game = other.post("/api/games", json={**EMPTY_SETUP, "companions": [PROFILE]}).json()
            self.factory.fail = True
            with self.assertLogs("fable.application.game_service", "ERROR"):
                self.assertEqual(events(other.post(f'/api/games/{game["id"]}/start'))[-1][0], "error")
            self.assertEqual(other.get(f'/api/games/{game["id"]}').json(), game)
