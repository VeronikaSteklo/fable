from enum import Enum
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ThinkingLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    XHIGH = "xhigh"


class ModelPrice(TypedDict):
    input: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    output: Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Settings(BaseSettings):
    api_key: str
    base_url: str
    model: str

    model_prices: dict[str, ModelPrice] = Field(default_factory=dict)

    llm_timeout_seconds: Annotated[float, Field(gt=0)] = 120
    llm_max_retries: Annotated[int, Field(ge=0)] = 2
    max_tool_rounds: Annotated[int, Field(ge=0)] = 8
    structured_output: Literal['json_schema', 'json_object', 'prompt'] = 'json_schema'
    enable_thinking: ThinkingLevel = ThinkingLevel.NONE
    temperature: Annotated[float, Field(ge=0, le=2)] = 0.7
    history_limit: Annotated[int, Field(ge=2)] = 16
    default_world: str = "Фэнтезийный мир, в котором древняя магия постепенно возвращается."
    default_story: str = "Герой оказывается перед загадкой, которая может изменить его жизнь."
    default_character_name: str = "Безымянный герой"
    default_character_role: str = "странник"
    default_character_goal: str = "раскрыть тайну"
    default_genre: str = "фэнтези"
    companion_model: str | None = None
    companion_temperature: Annotated[float, Field(ge=0, le=2)] = 0.8
    companions_enabled: bool = True
    summary_enabled: bool = True
    summary_max_chars: Annotated[int, Field(ge=1)] = 2000
    summary_model: str | None = None
    consistency_check_enabled: bool = True
    consistency_model: str | None = None
    sessions_path: Path = Path(__file__).resolve().parents[2] / ".fable" / "sessions"
    auth_db_path: Path = Path(__file__).resolve().parents[2] / ".fable" / "fable.db"
    session_ttl_days: Annotated[int, Field(ge=1)] = 30
    cookie_secure: bool = False
    allow_registration: bool = True
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
