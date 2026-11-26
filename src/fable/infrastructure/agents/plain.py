"""Plain continuation baseline: no bound tools and no mutable state access."""
from collections.abc import Iterator

from fable.infrastructure.llm.client import ChatModel, build_client, thinking_extra_body


class PlainStreamingAgent:
    def __init__(self, model: ChatModel, system_prompt: str) -> None:
        self._model = model
        self._prompt = system_prompt

    @classmethod
    def from_settings(cls, settings, system_prompt: str):
        return cls(ChatModel(build_client(settings), settings.model, settings.temperature,
                             thinking_extra_body(settings)), system_prompt)

    def stream(self, messages: list[dict]) -> Iterator[str]:
        yield from self._model.stream([{'role': 'system', 'content': self._prompt}, *messages])
