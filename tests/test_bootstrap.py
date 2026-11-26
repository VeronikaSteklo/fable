import unittest
from unittest.mock import patch

from fable.config import Settings
from fable.domain.models import Character, GameSetup
from fable.domain.state import GameState
from fable import bootstrap


def settings(**kwargs):
    return Settings(_env_file=None, api_key="test", base_url="http://example.invalid/v1",
                    model="master", moderation_enabled=False, **kwargs)


class BootstrapTests(unittest.TestCase):
    def test_defaults_preserve_explicit_fields_and_context_tracks_live_state(self):
        config = settings()
        setup = GameSetup("", "Завязка", Character("", "Следопыт", "", "Описание", ""))
        defaulted = bootstrap.apply_setup_defaults(setup, config)
        self.assertEqual(defaulted.world, config.default_world)
        self.assertEqual(defaulted.character.name, config.default_character_name)
        self.assertEqual(defaulted.character.goal, config.default_character_goal)
        self.assertEqual(defaulted.character.genre, config.default_genre)
        self.assertEqual(defaulted.character.role, "Следопыт")
        self.assertEqual(defaulted.story, "Завязка")
        state = GameState()
        provider = bootstrap.create_context_provider(defaulted, state)
        for text in [defaulted.world, defaulted.story, *defaulted.character.to_dict().values()]:
            self.assertIn(text, provider())
        state.update(location="Башня", add_inventory=["Ключ"], add_facts=["Дверь закрыта"])
        for text in ["Башня", "Ключ", "Дверь закрыта"]:
            self.assertIn(text, provider())

    def test_factory_wires_models_and_restores_snapshot(self):
        config = settings(summary_model="summary", consistency_model="checker", summary_max_chars=123)
        setup = bootstrap.apply_setup_defaults(GameSetup("", "", Character("", "", "", "", "")), config)
        state = GameState()
        with patch.object(bootstrap, "GameMasterAgent") as agent, patch.object(bootstrap, "ChatOpenAI") as model:
            agent.return_value.stream.return_value = iter(["Начало"])
            session = bootstrap.create_session(config, setup, state)
            self.assertEqual(session.start(), "Начало")
            restored = bootstrap.create_session(config, setup, state, session.to_snapshot())
            self.assertTrue(restored.started)
            self.assertIs(agent.call_args.args[2], state)
            self.assertEqual([c.kwargs["model"] for c in model.call_args_list],
                             ["summary", "checker", "summary", "checker"])
            self.assertTrue(all(c.kwargs["temperature"] == 0 for c in model.call_args_list))
            self.assertEqual(session._summarizer._max_chars, 123)

    def test_disabled_features_and_optional_vector_memory(self):
        config = settings(summary_enabled=False, consistency_check_enabled=False,
                          embedding_model="embeddings", embedding_base_url="http://embeddings.invalid/v1")
        setup = GameSetup("Мир", "Завязка", Character("Герой", "Роль", "Цель", "Описание", "Жанр"))
        state = GameState()
        with patch.object(bootstrap, "GameMasterAgent") as agent, \
                patch.object(bootstrap, "ChatOpenAI") as model, \
                patch.object(bootstrap, "OpenAIEmbeddings") as embeddings, \
                patch.object(bootstrap, "ChromaMemory") as memory:
            session = bootstrap.create_session(config, setup, state)
            self.assertIsNone(session._summarizer)
            self.assertIsNone(session._checker)
            model.assert_not_called()
            self.assertEqual(embeddings.call_args.kwargs["model"], "embeddings")
            self.assertEqual(embeddings.call_args.kwargs["base_url"], config.embedding_base_url)
            self.assertIs(memory.call_args.kwargs["setup"], setup)
            self.assertIs(agent.call_args.args[3], memory.return_value)
            self.assertIn("search_story_memories", agent.call_args.args[1])

    def test_required_settings_reject_blank_values(self):
        config = settings().model_copy(update={"api_key": " ", "model": ""})
        with self.assertRaisesRegex(ValueError, "API_KEY.*MODEL"):
            bootstrap.validate_settings(config)
