import json
import logging
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

logger = logging.getLogger(__name__)
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", re.ASCII)


class JsonSessionStore:
    def __init__(self, directory: Path) -> None:
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)

    def for_user(self, user_id: str) -> "JsonSessionStore":
        """Return an isolated namespace without exposing legacy root saves."""
        if not isinstance(user_id, str) or not _SAFE_ID.fullmatch(user_id):
            raise ValueError("Некорректный идентификатор пользователя")
        directory = self._directory / user_id
        if directory.is_symlink():
            raise ValueError("Каталог пользователя не может быть символической ссылкой")
        return JsonSessionStore(directory)

    def _path(self, game_id: str) -> Path:
        if not isinstance(game_id, str) or not _SAFE_ID.fullmatch(game_id):
            raise ValueError("Некорректный идентификатор игры")
        path = self._directory / f"{game_id}.json"
        if path.is_symlink():
            raise ValueError("Файл сессии не может быть символической ссылкой")
        return path

    def save(self, game_id: str, record: dict) -> None:
        target = self._path(game_id)
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self._directory,
                prefix=f".{game_id}-", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(record, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def load(self, game_id: str) -> dict | None:
        target = self._path(game_id)
        try:
            with target.open(encoding="utf-8") as stream:
                record = json.load(stream)
        except FileNotFoundError:
            return None
        if not isinstance(record, dict):
            raise ValueError("Файл сессии должен содержать объект JSON")
        return record

    def list(self) -> list[dict]:
        entries = []
        for path in self._directory.glob("*.json"):
            try:
                record = self.load(path.stem)
                if record is None:
                    continue
                character = record["setup"]["character"]["name"]
                history = record["session"]["history"]
                # A turn is a completed player action/reply, excluding the opening.
                turns = sum(
                    before["role"] == "user" and after["role"] == "assistant"
                    for before, after in zip(history[1:], history[2:])
                )
                entries.append({
                    "id": path.stem,
                    "title": record.get("title") or character,
                    "character_name": character,
                    "updated_at": record["updated_at"],
                    "turns": turns,
                })
            except (OSError, ValueError, KeyError, TypeError):
                logger.warning("Не удалось прочитать сессию %s", path.name, exc_info=True)
        return sorted(entries, key=lambda item: item["updated_at"], reverse=True)

    def delete(self, game_id: str) -> None:
        self._path(game_id).unlink(missing_ok=True)
