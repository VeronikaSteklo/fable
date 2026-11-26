from typing import Protocol

from fable.domain.companion import Companion, CompanionState


class CompanionVoice(Protocol):
    def speak(self, companion: CompanionState, profile: Companion, situation: str) -> str: ...
