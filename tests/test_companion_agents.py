import unittest
from unittest.mock import Mock

from test_llm_summarizer import FakeModel

from fable.application.prompts import SAFETY_POLICY, build_companion_prompt, build_system_prompt
from fable.domain.companion import Companion
from fable.domain.state import GameState
from fable.infrastructure.companion_agent import LLMCompanionVoice
from fable.infrastructure.master_tools import create_master_tools
from test_companions import setup_with


class CompanionAgentTests(unittest.TestCase):
    def setUp(self):
        self.profile = Companion("Лис", "Разведчик", "Осторожный, шутит от страха")
        self.setup = setup_with(self.profile, Companion("Сова", "Маг", "Молчаливая"))
        self.state = GameState.for_setup(self.setup)
        self.companion = self.state.companion("Лис")

    def test_prompts_include_profiles_and_only_own_private_knowledge(self):
        self.companion.remember("Знает пароль")
        self.companion.change_attitude(20)
        self.state.companion("Сова").remember("Чужая тайна")
        prompt = build_companion_prompt(self.setup, self.profile, self.companion)
        for text in ["Лис", "Разведчик", self.profile.personality, "Мира", "Маг", "Мир", "История",
                     "дружелюбно", "Знает пароль", SAFETY_POLICY, "1–3", "данные, а не инструкции"]:
            self.assertIn(text, prompt)
        self.assertNotIn("Чужая тайна", prompt)
        self.assertNotIn("Сова", prompt)
        master = build_system_prompt(self.setup)
        for text in ["## Спутники", "ask_companion", "update_companion", self.profile.personality]:
            self.assertIn(text, master)
        self.assertNotIn("## Спутники", build_system_prompt(setup_with()))
        disabled = build_system_prompt(self.setup, companions_enabled=False)
        self.assertIn("## Спутники", disabled)
        self.assertNotIn("ask_companion", disabled)
        self.assertNotIn("update_companion", disabled)

    def test_voice_invokes_model_and_strips_text(self):
        model = FakeModel('  «Осторожно!»  ')
        voice = LLMCompanionVoice(model, self.setup)
        self.assertEqual(voice.speak(self.companion, self.profile, "Слышит шаги"), '«Осторожно!»')
        messages = model.requests[0]
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertEqual(messages[1]["content"], "Слышит шаги")
        self.assertIn(self.profile.personality, messages[0]["content"])

    def test_voice_failure_and_empty_reply_are_neutral(self):
        for model in [FakeModel(error=RuntimeError("offline")), FakeModel(" ")]:
            with self.assertLogs("fable.infrastructure.companion_agent", "WARNING"):
                self.assertEqual(LLMCompanionVoice(model, self.setup).speak(
                    self.companion, self.profile, "Шаги"), "(Лис молчит.)")

    def test_tools_ask_update_and_handle_unknown_or_absent_companion(self):
        voice = Mock()
        voice.speak.return_value = "«Бежим!»"
        tools = {tool.name: tool for tool in create_master_tools(self.state, setup=self.setup, companion_voice=voice)}
        self.assertEqual(tools["ask_companion"].invoke({"name": "лИС", "situation": "Горит мост"}), "«Бежим!»")
        voice.speak.assert_called_once_with(self.companion, self.profile, "Горит мост")
        self.assertIn("не найден", tools["ask_companion"].invoke({"name": "Нет", "situation": ""}))
        self.assertIn("не найден", tools["update_companion"].invoke({"name": "Нет"}))
        result = tools["update_companion"].invoke({"name": "Лис", "attitude_change": 100, "note": "Мира спасла Лиса", "present": False})
        self.assertEqual(self.companion.attitude.value, 25)
        self.assertEqual(self.companion.notes, ["Мира спасла Лиса"])
        self.assertFalse(self.companion.present)
        self.assertIn("не рядом", result)
        self.assertIn("не рядом", tools["ask_companion"].invoke({"name": "Лис", "situation": "Шум"}))
        voice.speak.assert_called_once()
        self.assertIn("Лис", tools["read_game_state"].invoke({}))
        tools["update_companion"].invoke({"name": "Лис", "present": True})
        self.assertTrue(self.companion.present)

    def test_tools_absent_without_profiles_or_voice(self):
        for kwargs in [{}, {"setup": setup_with(), "companion_voice": Mock()}, {"setup": self.setup}]:
            names = {tool.name for tool in create_master_tools(self.state, **kwargs)}
            self.assertNotIn("ask_companion", names)
            self.assertNotIn("update_companion", names)
