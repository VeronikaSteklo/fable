from copy import deepcopy
import unittest

from fable.application.guardrails import RuleGuardrail
from fable.domain.models import GameSetup
from test_web import EMPTY_SETUP, FakeFactory
from test_bootstrap import settings


class MemoryRepository:
    def __init__(self):
        self.records = {}
        self.fail_save = False

    def get(self, game_id):
        return deepcopy(self.records.get(game_id))

    def add(self, stored):
        self.save(stored)

    def save(self, stored):
        if self.fail_save:
            raise OSError("disk full")
        self.records[stored.game.id] = deepcopy(stored)

    def delete(self, game_id):
        self.records.pop(game_id, None)

    def list_summaries(self):
        return [{"id": key} for key in self.records]


class GameServiceTests(unittest.TestCase):
    def setUp(self):
        from fable.application.game_service import GameService
        self.repository = MemoryRepository()
        self.factory = FakeFactory()
        self.service = GameService(
            repository_factory=lambda owner: self.repository,
            session_factory=lambda setup, state, snapshot: self.factory(settings(), setup, state, snapshot),
            guardrail=RuleGuardrail(), clock=lambda: "now", id_factory=lambda: "game",
        )
        self.setup = GameSetup.from_dict(EMPTY_SETUP)

    def test_successful_turn_attaches_events_and_empty_turn_omits_history_key(self):
        from fable.application.game_service import TurnCompleted, Chunk, GameAlreadyStarted, GameNotStarted
        loaded = self.service.create_game("owner", self.setup)
        with self.assertRaises(GameNotStarted):
            self.service.play_turn_stream("owner", "game", "Жду")
        items = list(self.service.start_stream("owner", "game"))
        self.assertIsInstance(items[0], Chunk)
        done = items[-1]
        self.assertIsInstance(done, TurnCompleted)
        self.assertEqual([event["type"] for event in done.events], ["location_changed", "fact_established"])
        self.assertEqual(loaded.session.to_snapshot()["history"][-1]["events"], done.events)
        self.assertEqual(self.repository.get("game").session["history"][-1]["events"], done.events)
        self.assertEqual(loaded.game.pull_events(), [])
        with self.assertRaises(GameAlreadyStarted):
            self.service.start_stream("owner", "game")
        done = list(self.service.play_turn_stream("owner", "game", "Жду"))[-1]
        self.assertEqual(done.events, [])
        self.assertNotIn("events", loaded.session.to_snapshot()["history"][-1])

    def test_busy_and_close_before_iteration_release_lock(self):
        from fable.application.game_service import GameBusy
        loaded = self.service.create_game("owner", self.setup)
        stream = self.service.start_stream("owner", "game")
        with self.assertRaises(GameBusy):
            self.service.start_stream("owner", "game")
        with self.assertRaises(GameBusy):
            self.service.delete_game("owner", "game")
        stream.close()
        stream.close()
        self.assertFalse(loaded.lock.locked())
        list(self.service.start_stream("owner", "game"))

    def test_failure_restores_state_session_and_drops_events(self):
        from fable.application.game_service import TurnFailed
        loaded = self.service.create_game("owner", self.setup)
        state = loaded.state
        before = loaded.session.to_snapshot()
        self.factory.fail = True
        with self.assertLogs("fable.application.game_service", "ERROR"):
            items = list(self.service.start_stream("owner", "game"))
        self.assertIsInstance(items[-1], TurnFailed)
        self.assertIs(loaded.state, state)
        self.assertIsNone(state.location)
        self.assertEqual(state.pull_events(), [])
        self.assertEqual(loaded.session.to_snapshot(), before)
        self.assertEqual(self.repository.get("game").session, before)
        self.factory.fail = False
        done = list(self.service.start_stream("owner", "game"))[-1]
        self.assertEqual(len(done.events), 2)

    def test_save_failure_and_cancel_roll_back_and_release(self):
        from fable.application.game_service import TurnFailed
        loaded = self.service.create_game("owner", self.setup)
        before = loaded.session.to_snapshot()
        stream = self.service.start_stream("owner", "game")
        next(stream)
        stream.close()
        self.assertEqual(loaded.session.to_snapshot(), before)
        self.assertIsNone(loaded.state.location)
        self.assertEqual(loaded.game.pull_events(), [])
        self.assertFalse(loaded.lock.locked())
        self.repository.fail_save = True
        with self.assertLogs("fable.application.game_service", "ERROR"):
            self.assertIsInstance(list(self.service.start_stream("owner", "game"))[-1], TurnFailed)
        self.assertEqual(loaded.session.to_snapshot(), before)
        self.assertEqual(loaded.game.pull_events(), [])
        self.assertFalse(loaded.lock.locked())

    def test_blocked_turn_leaves_history_unchanged(self):
        from fable.application.game_service import TurnBlocked
        loaded = self.service.create_game("owner", self.setup)
        list(self.service.start_stream("owner", "game"))
        before = loaded.session.to_snapshot()
        self.assertIsInstance(list(self.service.play_turn_stream("owner", "game", "sexual minor"))[-1], TurnBlocked)
        self.assertEqual(loaded.session.to_snapshot(), before)
        self.assertEqual(loaded.game.pull_events(), [])
        self.assertFalse(loaded.lock.locked())

    def test_create_and_rejected_setup(self):
        from fable.application.game_service import SetupRejected, InvalidSetup, GameNotFound
        from fable.domain.companion import Companion
        from dataclasses import replace
        with self.assertRaises(SetupRejected):
            self.service.create_game("owner", replace(self.setup, world="sexual minor"))
        self.assertEqual(self.repository.records, {})
        with self.assertRaises(InvalidSetup):
            self.service.create_game("owner", replace(self.setup, companions=(Companion("", "", ""),)))
        game = self.service.create_game("owner", self.setup)
        self.assertEqual(game.game.owner_id, "owner")
        self.assertEqual(self.service.list_games("owner"), [{"id": "game"}])
        self.assertIs(self.service.get_game("owner", "game"), game)
        with self.assertRaises(GameNotFound):
            self.service.get_game("owner", "missing")
        self.service.delete_game("owner", "game")
        with self.assertRaises(GameNotFound):
            self.service.get_game("owner", "game")
