from collections.abc import Iterator
from typing import Protocol

from fable.application.guardrails import Guardrail
from fable.application.prompts import build_start_prompt
from fable.domain.safety import ContentBlockedError


class StreamingAgent(Protocol):
    def stream(self, messages: list[dict]) -> Iterator[str]: ...


class GameSession:
    def __init__(
        self,
        agent: StreamingAgent,
        history_limit: int,
        guardrail: Guardrail | None = None,
    ):
        self._agent = agent
        self._guardrail = guardrail
        self._history_limit = history_limit
        self._history: list[dict] = [{"role": "user", "content": build_start_prompt()}]

    def start(self) -> str:
        return "".join(self.start_stream())

    def start_stream(self) -> Iterator[str]:
        reply = yield from self._stream_reply()
        self._history.append({"role": "assistant", "content": reply})

    def send_action(self, action: str) -> str:
        return "".join(self.send_action_stream(action))

    def send_action_stream(self, action: str) -> Iterator[str]:
        if self._guardrail is not None:
            verdict = self._guardrail.check(action)
            if not verdict.allowed:
                raise ContentBlockedError(verdict)

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
        for chunk in self._agent.stream(self._messages_for_request()):
            chunks.append(chunk)
            yield chunk
        return "".join(chunks)

    def _messages_for_request(self) -> list[dict]:
        if len(self._history) <= self._history_limit:
            return self._history
        return [self._history[0], *self._history[-(self._history_limit - 1) :]]
