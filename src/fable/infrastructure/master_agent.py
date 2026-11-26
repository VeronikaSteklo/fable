"""Streaming OpenAI tool loop. Only assistant content is public scene text."""
from collections.abc import Iterator

from fable.application.companions import CompanionVoice
from fable.application.ports import StoryMemory
from fable.config import Settings
from fable.domain.models import GameSetup
from fable.domain.state import GameState
from fable.infrastructure.master_tools import create_master_tools
from fable.infrastructure.openai_client import ChatModel, build_client, thinking_extra_body


class GameMasterAgent:
    def __init__(self, settings: Settings, system_prompt: str, game_state: GameState,
                 memory: StoryMemory | None = None, *, setup: GameSetup | None = None,
                 companion_voice: CompanionVoice | None = None) -> None:
        self._model = ChatModel(build_client(settings), settings.model, settings.temperature,
                                thinking_extra_body(settings))
        self._prompt = system_prompt
        self._state = game_state
        self._max_tool_rounds = settings.max_tool_rounds
        self._tools = create_master_tools(game_state, memory, setup=setup,
                                         companion_voice=companion_voice if settings.companions_enabled else None)
        # TODO: opt-in usage accounting for evaluation, without breaking local servers.

    def stream(self, messages: list[dict]) -> Iterator[str]:
        conversation = [{'role': 'system', 'content': self._prompt}, *[dict(m) for m in messages]]
        by_name = {tool.name: tool for tool in self._tools}
        for round_index in range(self._max_tool_rounds + 1):
            final = round_index == self._max_tool_rounds
            options = {'tools': [tool.to_openai() for tool in self._tools], 'stream': True}
            if final:
                options['tool_choice'] = 'none'
            stream = self._model.create(conversation, **options)
            calls: dict[int, dict] = {}
            content = []
            finish_reason = None
            try:
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason
                    delta = choice.delta
                    if delta.content:
                        content.append(delta.content)
                        yield delta.content
                    for part in delta.tool_calls or []:
                        call = calls.setdefault(part.index, {'id': '', 'type': 'function',
                                                           'function': {'name': '', 'arguments': ''}})
                        if part.id:
                            call['id'] += part.id
                        if part.function:
                            if part.function.name:
                                call['function']['name'] += part.function.name
                            if part.function.arguments:
                                call['function']['arguments'] += part.function.arguments
            finally:
                if hasattr(stream, 'close'):
                    stream.close()
            if final or finish_reason != 'tool_calls' or not calls:
                return
            tool_calls = [calls[index] for index in sorted(calls)]
            conversation.append({'role': 'assistant', 'content': ''.join(content) or None,
                                 'tool_calls': tool_calls})
            for call in tool_calls:
                name = call['function']['name']
                tool = by_name.get(name)
                result = (tool.invoke(call['function']['arguments']) if tool else
                          f'Ошибка: неизвестный инструмент «{name}».')
                conversation.append({'role': 'tool', 'tool_call_id': call['id'], 'content': result})
