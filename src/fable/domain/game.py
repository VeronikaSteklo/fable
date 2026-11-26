"""The campaign aggregate root; runtime agents and history live outside the domain."""
from dataclasses import dataclass

from fable.domain.events import DomainEvent
from fable.domain.models import GameSetup
from fable.domain.state import GameState


@dataclass
class Game:
    id: str
    owner_id: str | None
    setup: GameSetup
    state: GameState
    created_at: str
    updated_at: str

    @classmethod
    def create(cls, id: str, owner_id: str | None, setup: GameSetup, now: str) -> "Game":
        setup.validate()
        return cls(id, owner_id, setup, GameState.for_setup(setup), now, now)

    def pull_events(self) -> list[DomainEvent]:
        return self.state.pull_events()
