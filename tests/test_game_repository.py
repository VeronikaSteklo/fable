from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fable.application.persistence import build_game_record
from fable.domain.game import Game
from fable.domain.models import GameSetup
from fable.infrastructure.session_store import JsonSessionStore
from test_web import EMPTY_SETUP, FakeFactory
from test_bootstrap import settings


class GameRepositoryTests(unittest.TestCase):
    def test_round_trip_and_legacy_records(self):
        from fable.infrastructure.game_repository import JsonGameRepository
        from fable.application.ports import StoredGame
        with TemporaryDirectory() as directory:
            store = JsonSessionStore(Path(directory))
            repository = JsonGameRepository(store)
            setup = GameSetup.from_dict(EMPTY_SETUP)
            game = Game.create("saved", "owner", setup, "then")
            session = FakeFactory()(settings(), setup, game.state)
            game.state.update(add_inventory=["Ключ"])
            repository.add(StoredGame(game, session.to_snapshot()))
            restored = repository.get("saved")
            self.assertEqual(restored.game, game)
            self.assertEqual(restored.session, session.to_snapshot())
            self.assertEqual(restored.game.pull_events(), [])
            self.assertEqual(repository.list_summaries()[0]["id"], "saved")
            legacy = build_game_record("legacy", setup, game.state, session)
            legacy["setup"].pop("companions")
            legacy["state"].pop("companions")
            store.save("legacy", legacy)
            restored = repository.get("legacy")
            self.assertIsNone(restored.game.owner_id)
            self.assertEqual(restored.game.state.companions, [])
            restored.game.state.update(location="Лес")
            repository.save(restored)
            self.assertEqual(repository.get("legacy").game.state.location, "Лес")
            repository.delete("saved")
            self.assertIsNone(repository.get("saved"))
