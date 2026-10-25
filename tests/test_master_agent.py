import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fable.config import Settings, ThinkingLevel
from fable.domain.state import GameState
from fable.infrastructure.master_agent import GameMasterAgent


class GameMasterAgentTests(unittest.TestCase):
    @patch("fable.infrastructure.master_agent.create_agent")
    @patch("fable.infrastructure.master_agent.ChatOpenAI")
    def test_configures_langchain_agent_and_streams_text_chunks(
        self, chat_openai_class, create_agent_mock
    ) -> None:
        agent_graph = create_agent_mock.return_value
        agent_graph.stream.return_value = [
            {
                "type": "messages",
                "data": (SimpleNamespace(text="Сцена "), {"langgraph_node": "model"}),
            },
            {"type": "updates", "data": {}},
            {
                "type": "messages",
                "data": (SimpleNamespace(text="готова"), {"langgraph_node": "model"}),
            },
        ]
        settings = Settings(
            base_url="http://localhost:8080/v1",
            model="test-model",
            api_key="test-key",
            enable_thinking=ThinkingLevel.XHIGH,
            temperature=0.25,
        )
        system_prompt = "Ты — мастер игры."
        game_state = GameState()

        master = GameMasterAgent(settings, system_prompt, game_state)
        messages = [{"role": "user", "content": "Начни историю"}]

        self.assertEqual(list(master.stream(messages)), ["Сцена ", "готова"])
        chat_openai_class.assert_called_once_with(
            model="test-model",
            base_url="http://localhost:8080/v1",
            api_key="test-key",
            temperature=0.25,
            extra_body={
                "chat_template_kwargs": {"enable_thinking": True},
                "reasoning_effort": "xhigh",
            },
        )
        create_agent_mock.assert_called_once()
        agent_config = create_agent_mock.call_args.kwargs
        self.assertIs(agent_config["model"], chat_openai_class.return_value)
        self.assertEqual(agent_config["system_prompt"], system_prompt)
        self.assertEqual(
            [tool.name for tool in agent_config["tools"]],
            ["read_game_state", "update_game_state"],
        )
        agent_graph.stream.assert_called_once_with(
            {"messages": messages},
            stream_mode="messages",
            version="v2",
        )


if __name__ == "__main__":
    unittest.main()
