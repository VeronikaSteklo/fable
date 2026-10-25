from dataclasses import dataclass
from enum import Enum


class RiskCategory(str, Enum):
    SEXUAL_MINORS = "sexual_minors"
    REAL_WORLD_HARM_INSTRUCTIONS = "real_world_harm_instructions"
    SELF_HARM_METHODS = "self_harm_methods"
    EXTREMIST_PROPAGANDA = "extremist_propaganda"
    HATE_AGAINST_REAL_GROUPS = "hate_against_real_groups"


@dataclass(frozen=True)
class SafetyVerdict:
    allowed: bool
    category: RiskCategory | None = None
    reason: str = ""

    @classmethod
    def allow(cls) -> "SafetyVerdict":
        return cls(allowed=True)

    @classmethod
    def block(cls, category: RiskCategory, reason: str = "") -> "SafetyVerdict":
        return cls(allowed=False, category=category, reason=reason)


class ContentBlockedError(Exception):
    def __init__(self, verdict: SafetyVerdict):
        super().__init__(verdict.reason or "Запрос отклонён правилами безопасности")
        self.verdict = verdict
