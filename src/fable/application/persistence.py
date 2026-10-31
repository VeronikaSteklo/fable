from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone

from fable.application.session import GameSession
from fable.domain.models import GameSetup
from fable.domain.state import GameState


@dataclass(frozen=True)
class GameRecord:
    id: str
    created_at: str
    updated_at: str
    setup: GameSetup
    state: GameState
    session: dict


def build_game_record(
    game_id: str,
    setup: GameSetup,
    state: GameState,
    session: GameSession,
    *,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> dict:
    updated = updated_at or datetime.now(timezone.utc).isoformat()
    return {
        "id": game_id,
        "created_at": created_at or updated,
        "updated_at": updated,
        "setup": setup.to_dict(),
        "state": state.to_dict(),
        "session": session.to_snapshot(),
    }


def parse_game_record(record: dict) -> GameRecord:
    return GameRecord(
        id=record["id"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
        setup=GameSetup.from_dict(record["setup"]),
        state=GameState.from_dict(record["state"]),
        session=deepcopy(record["session"]),
    )
