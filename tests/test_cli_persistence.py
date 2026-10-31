from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fable.application.persistence import build_game_record
from fable.domain.models import GameSetup
from fable.domain.state import GameState
from fable.infrastructure.session_store import JsonSessionStore
from fable.presentation import cli
from test_bootstrap import settings
from test_web import EMPTY_SETUP, FakeFactory


class CLIPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = settings(sessions_path=Path(self.directory.name))
        self.store = JsonSessionStore(self.config.sessions_path)
        self.factory = FakeFactory()
        self.setup = GameSetup.from_dict(EMPTY_SETUP)

    def run_cli(self, answers):
        output = StringIO()
        with patch.object(cli, "load_settings", return_value=self.config), \
                patch.object(cli, "create_session", side_effect=self.factory), \
                patch.object(cli, "_create_game_setup", return_value=self.setup), \
                patch("builtins.input", side_effect=answers), redirect_stdout(output):
            cli.main()
        return output.getvalue()

    def test_new_game_saves_opening_and_each_reply(self):
        self.run_cli(["Осматриваюсь", "выход"])
        saved = self.store.list()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["turns"], 1)
        record = self.store.load(saved[0]["id"])
        self.assertEqual(record["setup"]["world"], self.config.default_world)
        self.assertEqual(len(record["session"]["history"]), 4)
        self.assertIn("consistency", record["session"]["history"][-1])

    def test_resume_prints_last_reply_and_preserves_created_at(self):
        state = GameState()
        session = self.factory(self.config, self.setup, state)
        session.start()
        record = build_game_record("saved", self.setup, state, session)
        self.store.save("saved", record)
        output = self.run_cli(["1", "Жду", "выход"])
        self.assertIn("Привет\nмир", output)
        self.assertIn("1.", output)
        saved = self.store.load("saved")
        self.assertEqual(saved["created_at"], record["created_at"])
        self.assertEqual(len(saved["session"]["history"]), 4)
        self.assertEqual(len(self.store.list()), 1)
