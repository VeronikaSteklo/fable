"""Shared composition root for terminal and HTTP entry points."""
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from pydantic import ValidationError

from fable.application.safety.guardrails import CompositeGuardrail, RuleGuardrail
from fable.application.prompts import build_system_prompt, render_prompt
from fable.application.game.session import GameSession
from fable.config import Settings
from fable.domain.game.setup import GameSetup
from fable.domain.game.state import GameState
from fable.infrastructure.memory.chroma import ChromaMemory
from fable.infrastructure.agents.companion import LLMCompanionVoice
from fable.infrastructure.checks.consistency import LLMConsistencyChecker
from fable.infrastructure.checks.moderator import LLMModerator
from fable.infrastructure.checks.summarizer import LLMSummarizer
from fable.infrastructure.agents.master import GameMasterAgent
from fable.infrastructure.llm.client import ChatModel, build_client
from fable.infrastructure.llm.embeddings import create_embeddings


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
    result = replace(
        setup,
        companions=tuple(
            replace(item, name=item.name.strip(), role=item.role.strip(), personality=item.personality.strip())
            for item in setup.companions
            if any(value.strip() for value in (item.name, item.role, item.personality))
        ),
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
    result.validate()
    return result


def setup_text(setup: GameSetup) -> str:
    return "\n".join([setup.world, setup.story, *setup.character.to_dict().values(),
                      *(value for item in setup.companions for value in item.to_dict().values())])


def create_guardrail(settings: Settings) -> CompositeGuardrail:
    guardrails: list = [RuleGuardrail()]
    if settings.moderation_enabled:
        guardrails.append(LLMModerator(_model(settings, settings.moderation_model)))
    return CompositeGuardrail(guardrails)


def _model(settings: Settings, model: str | None, *, temperature: float = 0) -> ChatModel:
    return ChatModel(client=build_client(settings), model=model or settings.model,
                     temperature=temperature, structured_output=settings.structured_output)


def create_context_provider(setup: GameSetup, state: GameState) -> Callable[[], str]:
    character = setup.character
    permanent = render_prompt(
        'narrative_context', world=setup.world, story=setup.story, genre=character.genre,
        name=character.name, role=character.role, goal=character.goal,
        description=character.description or 'не указано',
    )
    if setup.companions:
        permanent += render_prompt('narrative_companions', profiles="\n".join(
            render_prompt('narrative_companion_profile', name=item.name,
                          role=item.role, personality=item.personality)
            for item in setup.companions
        ))
    return lambda: permanent + "\n\n" + state.to_context()


def create_session(settings: Settings, setup: GameSetup, state: GameState,
                   snapshot: dict | None = None) -> GameSession:
    validate_settings(settings)
    setup.validate()
    memory = None
    if settings.embedding_model:
        memory = ChromaMemory(
            setup=setup,
            embeddings=create_embeddings(settings),
            persist_directory=settings.memory_store_path,
            search_limit=settings.memory_search_limit,
        )
    voice = (LLMCompanionVoice(
        _model(settings, settings.companion_model, temperature=settings.companion_temperature), setup,
    ) if setup.companions and settings.companions_enabled else None)
    agent = GameMasterAgent(settings, build_system_prompt(
        setup, vector_memory_enabled=memory is not None, companions_enabled=settings.companions_enabled,
    ), state, memory, setup=setup, companion_voice=voice)
    options: dict[str, Any] = dict(
        agent=agent, history_limit=settings.history_limit, guardrail=create_guardrail(settings),
        summarizer=(LLMSummarizer(_model(settings, settings.summary_model), settings.summary_max_chars)
                    if settings.summary_enabled else None),
        checker=(LLMConsistencyChecker(_model(settings, settings.consistency_model))
                 if settings.consistency_check_enabled else None),
        context_provider=create_context_provider(setup, state), model_prices=settings.model_prices,
    )
    if snapshot is not None:
        return GameSession.from_snapshot(snapshot, **options)
    return GameSession(**options)
