import logging
from collections.abc import Callable, Iterator
from copy import deepcopy
from typing import Protocol

from fable.application.consistency import ConsistencyChecker
from fable.application.guardrails import Guardrail
from fable.application.prompts import build_start_prompt
from fable.application.summary import Summarizer
from fable.domain.consistency import ConsistencyVerdict
from fable.domain.safety import ContentBlockedError

logger = logging.getLogger(__name__)


class StreamingAgent(Protocol):
    def stream(self, messages: list[dict]) -> Iterator[str]: ...


class GameSession:
    def __init__(
        self,
        agent: StreamingAgent,
        history_limit: int,
        guardrail: Guardrail | None = None,
        *,
        summarizer: Summarizer | None = None,
        checker: ConsistencyChecker | None = None,
        context_provider: Callable[[], str] | None = None,
    ) -> None:
        if history_limit < 2:
            raise ValueError("Лимит истории должен быть не меньше 2")
        self._checker = checker
        self._context_provider = context_provider
        self._last_verdict: ConsistencyVerdict | None = None
        self._pending_note = ""
        self._summarizer = summarizer
        self._summary = ""
        self._summarized_count = 0
        self._agent = agent
        self._guardrail = guardrail
        self._history_limit = history_limit
        self._history: list[dict] = [{"role": "user", "content": build_start_prompt()}]

    def start(self) -> str:
        return "".join(self.start_stream())

    def start_stream(self) -> Iterator[str]:
        reply = yield from self._stream_reply()
        self._record_reply(reply)

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

        self._record_reply(reply)
        return

    def _stream_reply(self) -> Iterator[str]:
        chunks: list[str] = []
        messages = self._messages_for_request()
        for chunk in self._agent.stream(messages):
            chunks.append(chunk)
            yield chunk
        self._pending_note = ""
        return "".join(chunks)

    def _record_reply(self, reply: str) -> None:
        entry: dict = {"role": "assistant", "content": reply}
        if self._checker is not None:
            try:
                context = self._context_provider() if self._context_provider else ""
                if self._summary:
                    context += "\n\nКраткое содержание прошлых событий:\n" + self._summary
                recent = self._plain_messages(self._history[-self._history_limit :])
                self._last_verdict = self._checker.check(context, recent, reply)
            except Exception:
                logger.warning("Проверка согласованности пропущена", exc_info=True)
                self._last_verdict = ConsistencyVerdict.ok()
            entry["consistency"] = {
                "consistent": self._last_verdict.consistent,
                "issues": list(self._last_verdict.issues),
            }
            if not self._last_verdict.consistent:
                issues = "; ".join(self._last_verdict.issues) or "Нарушена согласованность"
                self._pending_note = (
                    "Замечание проверки согласованности к прошлому ответу: " + issues
                    + ". Учти и исправь в продолжении, не упоминая проверку."
                )
        self._history.append(entry)

    @property
    def started(self) -> bool:
        return any(message["role"] == "assistant" for message in self._history)

    @property
    def last_verdict(self) -> ConsistencyVerdict | None:
        return self._last_verdict

    @property
    def summary(self) -> str:
        return self._summary

    def to_snapshot(self) -> dict:
        return {
            "history": deepcopy(self._history),
            "summary": self._summary,
            "summarized_count": self._summarized_count,
            "pending_note": self._pending_note,
            "last_verdict": ({"consistent": self._last_verdict.consistent,
                              "issues": list(self._last_verdict.issues)}
                             if self._last_verdict is not None else None),
        }

    @classmethod
    def from_snapshot(
        cls,
        snapshot: dict,
        *,
        agent: StreamingAgent,
        history_limit: int,
        guardrail: Guardrail | None = None,
        summarizer: Summarizer | None = None,
        checker: ConsistencyChecker | None = None,
        context_provider: Callable[[], str] | None = None,
    ) -> "GameSession":
        history = snapshot.get("history")
        count = snapshot.get("summarized_count", 0)
        summary = snapshot.get("summary", "")
        note = snapshot.get("pending_note", "")
        if (
            not isinstance(history, list) or not history
            or any(not isinstance(item, dict)
                   or item.get("role") not in {"user", "assistant"}
                   or not isinstance(item.get("content"), str) for item in history)
            or history[0]["role"] != "user"
            or type(count) is not int or not 0 <= count < len(history)
            or not isinstance(summary, str) or not isinstance(note, str)
            or (count > 0 and (not summary or history[count]["role"] != "assistant"))
        ):
            raise ValueError("Некорректный снимок сессии")
        session = cls(agent, history_limit, guardrail, summarizer=summarizer,
                      checker=checker, context_provider=context_provider)
        session._history = deepcopy(history)
        session._summary = summary
        session._summarized_count = count
        session._pending_note = note
        verdict = snapshot.get("last_verdict")
        if verdict is not None:
            if (not isinstance(verdict, dict)
                or type(verdict.get("consistent")) is not bool
                or not isinstance(verdict.get("issues"), list)
                or not all(isinstance(issue, str) for issue in verdict["issues"])):
                raise ValueError("Некорректный результат проверки согласованности")
            session._last_verdict = ConsistencyVerdict(
                verdict["consistent"], tuple(verdict["issues"])
            )
        return session

    @staticmethod
    def _plain_messages(messages: list[dict]) -> list[dict]:
        return [{"role": item["role"], "content": item["content"]} for item in messages]

    def _summarize_history(self) -> None:
        raw = self._history[1 + self._summarized_count :]
        if self._summarizer is None or len(raw) <= self._history_limit:
            return
        # Keep roughly half the window raw; cut only after an assistant reply,
        # so a user action and its reply are never summarized separately.
        cutoff = len(raw) - max(2, self._history_limit // 2)
        while cutoff > 0 and raw[cutoff - 1]["role"] != "assistant":
            cutoff -= 1
        if not cutoff:
            return
        try:
            summary = self._summarizer.summarize(
                self._summary, self._plain_messages(raw[:cutoff])
            )
        except Exception:
            logger.warning("Не удалось сжать историю; повторим позже", exc_info=True)
            return
        if not isinstance(summary, str) or not summary.strip() or summary == self._summary:
            return
        self._summary = summary
        self._summarized_count += cutoff

    def _messages_for_request(self) -> list[dict]:
        self._summarize_history()
        first = self._plain_messages(self._history[:1])[0]
        if self._summary:
            first["content"] += "\n\nКраткое содержание прошлых событий:\n" + self._summary
        raw = self._history[1 + self._summarized_count :]
        messages = [first, *self._plain_messages(raw[-(self._history_limit - 1) :])]
        if self._pending_note:
            messages.append({"role": "user", "content": self._pending_note})
        return messages
