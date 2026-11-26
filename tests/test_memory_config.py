from pathlib import Path
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from fable.application.prompts import build_system_prompt
from fable.config import Settings
from fable.domain.models import Character, GameSetup


class MemoryConfigTests(unittest.TestCase):
    def test_memory_settings_defaults(self):
        with patch.dict("os.environ", {}, clear=True):
            settings = Settings(api_key="", base_url="", model="", _env_file=None)
        self.assertTrue(settings.summary_enabled)
        self.assertEqual(settings.summary_max_chars, 2000)
        self.assertIsNone(settings.summary_model)
        self.assertTrue(settings.consistency_check_enabled)
        self.assertIsNone(settings.consistency_model)
        self.assertEqual(settings.sessions_path, Path(__file__).resolve().parents[1] / ".fable" / "sessions")

    def test_memory_settings_can_be_overridden_and_size_must_be_positive(self):
        with patch.dict("os.environ", {"SUMMARY_ENABLED":"false", "SUMMARY_MAX_CHARS":"500",
                                      "SUMMARY_MODEL":"summary", "CONSISTENCY_CHECK_ENABLED":"false",
                                      "CONSISTENCY_MODEL":"checker", "SESSIONS_PATH":"saved"}, clear=True):
            settings = Settings(api_key="", base_url="", model="", _env_file=None)
        self.assertFalse(settings.summary_enabled)
        self.assertEqual(settings.summary_max_chars, 500)
        self.assertEqual(settings.summary_model, "summary")
        self.assertFalse(settings.consistency_check_enabled)
        self.assertEqual(settings.consistency_model, "checker")
        self.assertEqual(settings.sessions_path, Path("saved"))
        with self.assertRaises(ValidationError):
            Settings(api_key="", base_url="", model="", summary_max_chars=0, _env_file=None)

    def test_system_prompt_requires_respecting_event_summary(self):
        setup = GameSetup("Мир", "История", Character("Мира", "Маг", "Цель", "", "Фэнтези"))
        prompt = build_system_prompt(setup)
        self.assertIn("Краткое содержание прошлых событий", prompt)
        self.assertIn("учитывай", prompt)
