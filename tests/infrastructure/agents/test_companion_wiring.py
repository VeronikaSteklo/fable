import unittest
from unittest.mock import patch

from pydantic import ValidationError

from fable import bootstrap
from fable.application.game.persistence import build_game_record, parse_game_record
from fable.application.game.session import GameSession
from fable.domain.companions.companion import Companion, InvalidSetupError
from fable.domain.game.state import GameState
from tests.application.test_bootstrap import settings
from tests.domain.companions.test_companions import setup_with
from tests.application.game.test_session import FakeAgent


class CompanionWiringTests(unittest.TestCase):
    def setUp(self):
        self.profile = Companion("Лис", "Разведчик", "Шутник")
        self.setup = setup_with(self.profile)

    def test_defaults_strip_and_drop_fully_empty_entries(self):
        setup = setup_with(Companion(" Лис ", " Разведчик ", " Шутник "), Companion(" ", "", " "))
        defaulted = bootstrap.apply_setup_defaults(setup, settings())
        self.assertEqual(defaulted.companions, (self.profile,))
        for text in ["Лис", "Разведчик", "Шутник"]:
            self.assertIn(text, bootstrap.setup_text(defaulted))
            self.assertIn(text, bootstrap.create_context_provider(defaulted, GameState())())
        with self.assertRaises(InvalidSetupError):
            bootstrap.apply_setup_defaults(setup_with(Companion("", "Разведчик", "")), settings())

    def test_factory_builds_voice_with_selected_model_and_temperature(self):
        for companion_model, expected in [(None, "master"), ("voice", "voice")]:
            with self.subTest(companion_model=companion_model):
                config = settings(companion_model=companion_model, companion_temperature=1.1,
                                  summary_enabled=False, consistency_check_enabled=False)
                state = GameState.for_setup(self.setup)
                with patch.object(bootstrap, "ChatModel") as model, patch.object(bootstrap, "GameMasterAgent") as master:
                    bootstrap.create_session(config, self.setup, state)
                    self.assertEqual(model.call_args.kwargs["model"], expected)
                    self.assertEqual(model.call_args.kwargs["temperature"], 1.1)
                    self.assertIs(master.call_args.kwargs["setup"], self.setup)
                    voice = master.call_args.kwargs["companion_voice"]
                    self.assertIs(voice._model, model.return_value)
                    self.assertIn("ask_companion", master.call_args.args[1])

    def test_disabled_companions_keep_state_but_have_no_voice(self):
        config = settings(companions_enabled=False, summary_enabled=False, consistency_check_enabled=False)
        state = GameState.for_setup(self.setup)
        with patch.object(bootstrap, "ChatModel") as model, patch.object(bootstrap, "GameMasterAgent") as master:
            bootstrap.create_session(config, self.setup, state)
            model.assert_not_called()
            self.assertIsNone(master.call_args.kwargs["companion_voice"])
            self.assertNotIn("ask_companion", master.call_args.args[1])
        self.assertEqual(len(state.companions), 1)

    def test_companion_settings_limits(self):
        self.assertTrue(settings().companions_enabled)
        self.assertEqual(settings().companion_temperature, 0.8)
        self.assertIsNone(settings().companion_model)
        for temperature in [-0.01, 2.01]:
            with self.assertRaises(ValidationError):
                settings(companion_temperature=temperature)

    def test_record_restoration_initializes_only_missing_companion_state(self):
        state = GameState.for_setup(self.setup)
        state.companion("Лис").change_attitude(15)
        state.companion("Лис").remember("Секрет")
        state.companion("Лис").set_present(False)
        record = build_game_record("game", self.setup, state, GameSession(FakeAgent(["Начало"]), 4))
        self.assertEqual(parse_game_record(record).state, state)
        record["state"].pop("companions")
        self.assertEqual(parse_game_record(record).state, GameState.for_setup(self.setup))
        record["state"]["companions"] = []
        self.assertEqual(parse_game_record(record).state.companions, [])
        record["setup"].pop("companions")
        record["state"].pop("companions")
        old = parse_game_record(record)
        self.assertEqual(old.setup.companions, ())
        self.assertEqual(old.state.companions, [])

    @patch("fable.infrastructure.agents.master.build_client")
    def test_master_receives_tools_and_honors_disabled_setting(self, model):
        from fable.infrastructure.agents.master import GameMasterAgent
        voice = object()
        for enabled in [True, False]:
            master = GameMasterAgent(settings(companions_enabled=enabled), "Промпт", GameState.for_setup(self.setup),
                            setup=self.setup, companion_voice=voice)
            names = {tool.name for tool in master._tools}
            self.assertEqual("ask_companion" in names, enabled)
            self.assertEqual("update_companion" in names, enabled)
