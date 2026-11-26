import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.outputs import ChatGenerationChunk

from fable.config import Settings
from fable.domain.companion import Companion
from fable.domain.state import GameState
from fable.infrastructure.companion_agent import LLMCompanionVoice
from fable.infrastructure.master_agent import GameMasterAgent
from test_companions import setup_with


class ScriptedToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        message = self._generate(messages).generations[0].message
        yield ChatGenerationChunk(message=AIMessageChunk(content=message.content, tool_calls=message.tool_calls))



class CompanionStreamingTests(unittest.TestCase):
    @patch("fable.infrastructure.master_agent.ChatOpenAI")
    def test_real_graph_orchestrates_companion_and_emits_tool_metadata(self, model):
        setup = setup_with(Companion("Лис", "Разведчик", "Осторожный"))
        state = GameState.for_setup(setup)
        model.return_value = ScriptedToolModel(responses=[
            AIMessage(content="", tool_calls=[{"name": "ask_companion", "args": {
                "name": "Лис", "situation": "Мира вытащила Лиса с горящего моста",
            }, "id": "ask", "type": "tool_call"}]),
            AIMessage(content="", tool_calls=[{"name": "update_companion", "args": {
                "name": "Лис", "attitude_change": 20, "note": "Мира спасла Лиса",
            }, "id": "update", "type": "tool_call"}]),
            AIMessage(content="Лис говорит: «Бежим!»"),
        ])
        voice_model = Mock()
        voice_model.invoke.return_value = SimpleNamespace(text="«Бежим!»")
        config = Settings(_env_file=None, api_key="test", base_url="http://invalid", model="test")
        master = GameMasterAgent(config, "Промпт", state, setup=setup,
                                 companion_voice=LLMCompanionVoice(voice_model, setup))
        events = list(master._agent.stream({"messages": [{"role": "user", "content": "Спасаю Лиса"}]},
                                          stream_mode="messages", version="v2"))
        tool_events = [(event["data"][0], event["data"][1]["langgraph_node"])
                       for event in events if isinstance(event["data"][0], ToolMessage)]
        self.assertEqual([node for _, node in tool_events], ["tools", "tools"])
        self.assertEqual(tool_events[0][0].content, "«Бежим!»")
        self.assertEqual(state.companion("Лис").attitude.value, 20)
        self.assertEqual(state.companion("Лис").notes, ["Мира спасла Лиса"])
        self.assertEqual(voice_model.invoke.call_count, 1)
        master._agent = SimpleNamespace(stream=lambda *args, **kwargs: iter(events))
        self.assertEqual("".join(master.stream([])), "Лис говорит: «Бежим!»")

    @patch("fable.infrastructure.master_agent.create_agent")
    @patch("fable.infrastructure.master_agent.ChatOpenAI")
    def test_only_model_ai_chunks_reach_scene(self, model, create_agent):
        create_agent.return_value.stream.return_value = [
            {"type": "messages", "data": (ToolMessage(content="Состояние обновлено", tool_call_id="1"), {"langgraph_node": "tools"})},
            {"type": "messages", "data": (ToolMessage(content="Не сцена", tool_call_id="2"), {"langgraph_node": "model"})},
            {"type": "messages", "data": (AIMessageChunk(content="Секрет спутника"), {"langgraph_node": "tools"})},
            {"type": "messages", "data": (AIMessageChunk(content="Нет метаданных"), {})},
            {"type": "messages", "data": (AIMessageChunk(content="Сцена"), {"langgraph_node": "model"})},
        ]
        config = Settings(_env_file=None, api_key="test", base_url="http://invalid", model="test")
        self.assertEqual(list(GameMasterAgent(config, "Промпт", GameState()).stream([])), ["Сцена"])
