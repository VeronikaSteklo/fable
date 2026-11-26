import unittest
from unittest.mock import patch

from fable.presentation.cli.main import _create_game_setup
from tests.application.test_bootstrap import settings


class CompanionCliTests(unittest.TestCase):
    def test_can_skip_companions(self):
        with patch("builtins.input", side_effect=[""] * 7 + ["н"]), patch("builtins.print"):
            self.assertEqual(_create_game_setup(settings()).companions, ())

    def test_invalid_profile_reprompts_then_accepts_companion(self):
        answers = [""] * 7 + ["д", "", "Маг", "Тихий", "Лис", " Разведчик ", " Шутник ", "н"]
        with patch("builtins.input", side_effect=answers) as ask, patch("builtins.print") as output:
            setup = _create_game_setup(settings())
        self.assertEqual(len(setup.companions), 1)
        self.assertEqual(setup.companions[0].to_dict(), {"name": "Лис", "role": "Разведчик", "personality": "Шутник"})
        self.assertTrue(any("Укажи имя" in str(call) for call in output.call_args_list))
        self.assertIn("Добавить спутника? (д/н)", ask.call_args_list[-1].args[0])

    def test_stops_after_three_and_rejects_duplicate_hero_name(self):
        config = settings()
        answers = ([""] * 7 + ["д", config.default_character_name, "", "", "Лис", "", "",
                                "д", "Сова", "", "", "д", "Кот", "", ""])
        with patch("builtins.input", side_effect=answers) as ask, patch("builtins.print"):
            setup = _create_game_setup(config)
        self.assertEqual([item.name for item in setup.companions], ["Лис", "Сова", "Кот"])
        self.assertEqual(sum("Добавить спутника" in call.args[0] for call in ask.call_args_list), 3)
