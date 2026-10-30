from enum import Enum
from pathlib import Path
from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ThinkingLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    XHIGH = "xhigh"


class Settings(BaseSettings):
    api_key: str
    base_url: str
    model: str

    enable_thinking: ThinkingLevel = ThinkingLevel.NONE
    temperature: Annotated[float, Field(ge=0, le=2)] = 0.7
    history_limit: Annotated[int, Field(ge=2)] = 16
    default_world: str = "Фэнтезийный мир, в котором древняя магия постепенно возвращается."
    default_story: str = "Герой оказывается перед загадкой, которая может изменить его жизнь."
    default_character_name: str = "Безымянный герой"
    default_character_role: str = "странник"
    default_character_goal: str = "раскрыть тайну"
    default_genre: str = "фэнтези"
    summary_enabled: bool = True
    summary_max_chars: Annotated[int, Field(ge=1)] = 2000
    summary_model: str | None = None
    consistency_check_enabled: bool = True
    consistency_model: str | None = None
    sessions_path: Path = Path(__file__).resolve().parents[2] / ".fable" / "sessions"
    moderation_enabled: bool = True
    moderation_model: str | None = None
    embedding_model: str | None = None
    embedding_base_url: str | None = None
    memory_store_path: Path = Path(__file__).resolve().parents[2] / ".fable" / "chroma"
    memory_search_limit: Annotated[int, Field(ge=1, le=10)] = 3

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
