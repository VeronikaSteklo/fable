import re
from collections.abc import Sequence
from typing import Protocol

from fable.domain.safety import RiskCategory, SafetyVerdict

BLOCK_MESSAGE = (
    "Это направление истории я продолжать не буду. "
    "Опиши другое действие — например, смени тему или ход сцены."
)

_MINOR = re.compile(
    r"\b(ребён\w*|ребен\w*|малолетн\w*|несовершеннолетн\w*|школьниц\w*|школьник\w*"
    r"|подрост\w*|девочк\w*|мальчик\w*|лоли\w*|шота\w*|\d{1,2}[- ]?летн\w*"
    r"|child\w*|minor\w*|underage|preteen\w*|loli\w*|kid\w*)",
    re.IGNORECASE,
)
_SEXUAL = re.compile(
    r"(секс\w*|сексуальн\w*|интим\w*|изнасил\w*|совращ\w*|разврат\w*|голы[йехм]\w*|обнажённ\w*"
    r"|эротик\w*|порн\w*|sex\w*|nude|naked|rape\w*|erotic\w*|porn\w*)",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"[.!?\n]+")


class Guardrail(Protocol):
    def check(self, text: str) -> SafetyVerdict: ...


class RuleGuardrail:
    """Дешёвая детерминированная проверка абсолютных запретов.

    Ловит только очевидные формулировки: сексуальный контекст и упоминание
    несовершеннолетнего в одном предложении. Остальное — задача модератора и промпта.
    """

    def check(self, text: str) -> SafetyVerdict:
        for sentence in _SENTENCE_SPLIT.split(text):
            if _MINOR.search(sentence) and _SEXUAL.search(sentence):
                return SafetyVerdict.block(
                    RiskCategory.SEXUAL_MINORS, "Сексуальный контент с участием несовершеннолетних"
                )
        return SafetyVerdict.allow()


class CompositeGuardrail:
    def __init__(self, guardrails: Sequence[Guardrail]):
        self._guardrails = tuple(guardrails)

    def check(self, text: str) -> SafetyVerdict:
        for guardrail in self._guardrails:
            verdict = guardrail.check(text)
            if not verdict.allowed:
                return verdict
        return SafetyVerdict.allow()
