"""Shared composition root for terminal and HTTP entry points."""
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import ValidationError

from fable.application.guardrails import CompositeGuardrail, RuleGuardrail
from fable.application.prompts import build_system_prompt
from fable.application.session import GameSession
from fable.config import Settings
from fable.domain.models import GameSetup
from fable.domain.state import GameState
from fable.infrastructure.chroma_memory import ChromaMemory
from fable.infrastructure.llm_consistency import LLMConsistencyChecker
from fable.infrastructure.llm_moderator import LLMModerator
from fable.infrastructure.llm_summarizer import LLMSummarizer
from fable.infrastructure.master_agent import GameMasterAgent


def validate_settings(settings: Settings) -> None:
    missing = [name.upper() for name in ("api_key", "base_url", "model")
               if not getattr(settings, name).strip()]
    if missing:
        raise ValueError("Заполни обязательные настройки в .env: " + ", ".join(missing))


def load_settings() -> Settings:
    try:
        settings = Settings()
    except ValidationError as error:
        missing = [str(item["loc"][0]).upper() for item in error.errors()
                   if item["type"] == "missing"]
        if missing:
            raise ValueError("Заполни обязательные настройки в .env: " + ", ".join(missing)) from error
        raise ValueError(f"Проверь настройки в .env: {error}") from error
    validate_settings(settings)
    return settings


def apply_setup_defaults(setup: GameSetup, settings: Settings) -> GameSetup:
    character = setup.character
    return replace(
        setup,
        world=setup.world.strip() or settings.default_world,
        story=setup.story.strip() or settings.default_story,
        character=replace(character, **{
            name: getattr(character, name).strip() or getattr(settings, default)
            for name, default in {
                "name": "default_character_name", "role": "default_character_role",
                "goal": "default_character_goal", "genre": "default_genre",
            }.items()
        }),
    )


def setup_text(setup: GameSetup) -> str:
    return "\n".join([setup.world, setup.story, setup.character.description, setup.character.goal])


def create_guardrail(settings: Settings) -> CompositeGuardrail:
    guardrails: list = [RuleGuardrail()]
    if settings.moderation_enabled:
        guardrails.append(LLMModerator(_model(settings, settings.moderation_model)))
    return CompositeGuardrail(guardrails)


def _model(settings: Settings, model: str | None) -> ChatOpenAI:
    return ChatOpenAI(model=model or settings.model, api_key=settings.api_key,
                      base_url=settings.base_url, temperature=0)


def create_context_provider(setup: GameSetup, state: GameState) -> Callable[[], str]:
    character = setup.character
    permanent = (
        f"Мир: {setup.world}\nЗавязка истории: {setup.story}\nЖанр: {character.genre}\n"
        f"Имя: {character.name}\nРоль: {character.role}\nЦель: {character.goal}\n"
        f"Описание: {character.description or 'не указано'}"
    )
    return lambda: permanent + "\n\n" + state.to_context()


def create_session(settings: Settings, setup: GameSetup, state: GameState,
                   snapshot: dict | None = None) -> GameSession:
    validate_settings(settings)
    memory = None
    if settings.embedding_model:
        memory = ChromaMemory(
            setup=setup,
            embeddings=OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.api_key,
                                        base_url=settings.embedding_base_url or settings.base_url),
            persist_directory=settings.memory_store_path,
            search_limit=settings.memory_search_limit,
        )
    agent = GameMasterAgent(settings, build_system_prompt(setup, vector_memory_enabled=memory is not None),
                            state, memory)
    options: dict[str, Any] = dict(
        agent=agent, history_limit=settings.history_limit, guardrail=create_guardrail(settings),
        summarizer=(LLMSummarizer(_model(settings, settings.summary_model), settings.summary_max_chars)
                    if settings.summary_enabled else None),
        checker=(LLMConsistencyChecker(_model(settings, settings.consistency_model))
                 if settings.consistency_check_enabled else None),
        context_provider=create_context_provider(setup, state),
    )
    if snapshot is not None:
        return GameSession.from_snapshot(snapshot, **options)
    return GameSession(**options)
