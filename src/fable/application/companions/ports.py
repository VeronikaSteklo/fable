from typing import Protocol

from fable.domain.companions.companion import Companion, CompanionState


class CompanionVoice(Protocol):
    def speak(self, companion: CompanionState, profile: Companion, situation: str) -> str: ...
