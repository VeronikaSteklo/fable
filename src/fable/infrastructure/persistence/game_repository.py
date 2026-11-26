"""Backward-compatible JSON adapter for the campaign repository port."""
from copy import deepcopy

from fable.application.game.persistence import parse_game_record
from fable.application.ports import StoredGame
from fable.domain.game.game import Game
from fable.infrastructure.persistence.session_store import JsonSessionStore


class JsonGameRepository:
    def __init__(self, store: JsonSessionStore) -> None:
        self.store = store

    def get(self, game_id: str) -> StoredGame | None:
        record = self.store.load(game_id)
        if record is None:
            return None
        parsed = parse_game_record(record)
        return StoredGame(Game(parsed.id, record.get("owner_id"), parsed.setup, parsed.state,
                               parsed.created_at, parsed.updated_at), parsed.session)

    def add(self, stored: StoredGame) -> None:
        self.save(stored)

    def save(self, stored: StoredGame) -> None:
        game = stored.game
        self.store.save(game.id, {
            "id": game.id, "owner_id": game.owner_id,
            "created_at": game.created_at, "updated_at": game.updated_at,
            "setup": game.setup.to_dict(), "state": game.state.to_dict(),
            "session": deepcopy(stored.session),
        })

    def delete(self, game_id: str) -> None:
        self.store.delete(game_id)

    def list_summaries(self) -> list[dict]:
        return self.store.list()
