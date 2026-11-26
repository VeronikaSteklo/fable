from collections.abc import Iterator

from fable.application.prompts import build_start_prompt, build_system_prompt
from fable.domain.models import GameSetup
from fable.infrastructure.llm_client import LLMClient


class GameSession:
    def __init__(self, setup: GameSetup, client: LLMClient):
        self._client = client
        self._history: list[dict] = [
            {"role": "system", "content": build_system_prompt(setup)},
            {"role": "user", "content": build_start_prompt()},
        ]

    def start(self) -> str:
        return "".join(self.start_stream())

    def start_stream(self) -> Iterator[str]:
        reply = yield from self._stream_reply()
        self._history.append({"role": "assistant", "content": reply})

    def send_action(self, action: str) -> str:
        return "".join(self.send_action_stream(action))

    def send_action_stream(self, action: str) -> Iterator[str]:
        self._history.append({"role": "user", "content": action})
        try:
            reply = yield from self._stream_reply()
        except Exception:
            self._history.pop()
            raise

        self._history.append({"role": "assistant", "content": reply})
        return

    def _stream_reply(self) -> Iterator[str]:
        chunks: list[str] = []
        for chunk in self._client.stream(self._messages_for_request()):
            chunks.append(chunk)
            yield chunk
        return "".join(chunks)

    def _messages_for_request(self) -> list[dict]:
        if len(self._history) <= 16:
            return self._history
        return [self._history[0], *self._history[-14:]]
