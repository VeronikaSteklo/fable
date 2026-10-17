import unittest
from unittest.mock import patch

from pydantic import ValidationError

from fable.config import Settings, ThinkingLevel


class SettingsTests(unittest.TestCase):
    def test_required_fields_are_required(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(_env_file=None)

    def test_optional_settings_use_model_defaults(self) -> None:
        settings = Settings(api_key="", base_url="", model="", _env_file=None)

        self.assertEqual(settings.enable_thinking, ThinkingLevel.NONE)
        self.assertEqual(settings.temperature, 0.7)
        self.assertEqual(settings.history_limit, 16)

    def test_environment_overrides_defaults(self) -> None:
        overrides = {
            "BASE_URL": "https://llm.example/v1",
            "MODEL": "story-model",
            "API_KEY": "secret-test-key",
            "ENABLE_THINKING": "xhigh",
            "TEMPERATURE": "0.35",
            "HISTORY_LIMIT": "24",
            "DEFAULT_GENRE": "мистика",
        }
        with patch.dict("os.environ", overrides, clear=True):
            settings = Settings(_env_file=None)

        self.assertEqual(settings.base_url, overrides["BASE_URL"])
        self.assertEqual(settings.model, overrides["MODEL"])
        self.assertEqual(settings.api_key, overrides["API_KEY"])
        self.assertEqual(settings.enable_thinking, ThinkingLevel.XHIGH)
        self.assertEqual(settings.temperature, 0.35)
        self.assertEqual(settings.history_limit, 24)
        self.assertEqual(settings.default_genre, "мистика")

    def test_rejects_invalid_thinking_level(self) -> None:
        with patch.dict("os.environ", {"ENABLE_THINKING": "sometimes"}, clear=True):
            with self.assertRaises(ValidationError):
                Settings(api_key="", base_url="", model="", _env_file=None)

    def test_accepts_all_thinking_enum_values(self) -> None:
        for level in ThinkingLevel:
            with self.subTest(level=level):
                with patch.dict("os.environ", {"ENABLE_THINKING": level.value}, clear=True):
                    settings = Settings(api_key="", base_url="", model="", _env_file=None)

                self.assertIs(settings.enable_thinking, level)

    def test_rejects_temperature_outside_supported_range(self) -> None:
        with patch.dict("os.environ", {"TEMPERATURE": "2.1"}, clear=True):
            with self.assertRaises(ValidationError):
                Settings(api_key="", base_url="", model="", _env_file=None)


if __name__ == "__main__":
    unittest.main()
