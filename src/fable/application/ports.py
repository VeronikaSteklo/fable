"""Shared application boundaries for agents, memory and campaign repositories."""
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from fable.domain.game.game import Game
from fable.application.usage import UsageMeter as UsageMeter, UsageRecord as UsageRecord, TokenUsage as TokenUsage

# Re-export established ports without forcing callers to migrate imports.
from fable.application.companions.ports import CompanionVoice as CompanionVoice
from fable.application.narrative.consistency import ConsistencyChecker as ConsistencyChecker
from fable.application.safety.guardrails import Guardrail as Guardrail
from fable.application.narrative.summary import Summarizer as Summarizer


@dataclass(frozen=True)
class StoredGame:
    """Persistence envelope: domain aggregate plus narrative session snapshot."""
    game: Game
    session: dict


class StreamingAgent(Protocol):
    def stream(self, messages: list[dict]) -> Iterator[str]: ...


class StoryMemory(Protocol):
    def remember(self, event: str) -> str: ...
    def search(self, query: str) -> list[str]: ...


class GameRepository(Protocol):
    """A repository is already scoped to one owner (or the legacy CLI root)."""
    def get(self, game_id: str) -> StoredGame | None: ...
    def add(self, stored: StoredGame) -> None: ...
    def save(self, stored: StoredGame) -> None: ...
    def delete(self, game_id: str) -> None: ...
    def list_summaries(self) -> list[dict]: ...
