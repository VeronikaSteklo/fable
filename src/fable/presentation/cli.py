from pydantic import ValidationError

from fable.application.guardrails import BLOCK_MESSAGE, CompositeGuardrail, RuleGuardrail
from fable.application.prompts import build_system_prompt
from fable.application.session import GameSession
from fable.config import Settings
from fable.domain.models import Character, GameSetup
from fable.domain.safety import ContentBlockedError
from fable.domain.state import GameState
from fable.infrastructure.chroma_memory import ChromaMemory
from fable.infrastructure.llm_moderator import LLMModerator
from fable.infrastructure.master_agent import GameMasterAgent
from langchain_openai import ChatOpenAI, OpenAIEmbeddings


def _create_character(settings: Settings) -> Character:
    print("=== Создание героя ===")
    print("Можно нажать Enter, чтобы использовать значения по умолчанию.\n")

    name = input("Имя персонажа: ").strip() or settings.default_character_name
    role = input("Роль: ").strip() or settings.default_character_role
    goal = input("Цель: ").strip() or settings.default_character_goal
    description = input("Опиши героя (можно оставить пустым): ").strip()
    genre = input("Жанр: ").strip() or settings.default_genre

    return Character(
        name=name,
        role=role,
        goal=goal,
        description=description,
        genre=genre,
    )


def _create_game_setup(settings: Settings) -> GameSetup:
    print("=== Создание игры ===")
    world = input("Опиши мир: ").strip() or settings.default_world
    story = input("Опиши завязку истории: ").strip() or settings.default_story

    return GameSetup(world=world, story=story, character=_create_character(settings))


def _create_guardrail(settings: Settings) -> CompositeGuardrail:
    guardrails: list = [RuleGuardrail()]
    if settings.moderation_enabled:
        moderator_model = ChatOpenAI(
            model=settings.moderation_model or settings.model,
            base_url=settings.base_url,
            api_key=settings.api_key,
            temperature=0,
        )
        guardrails.append(LLMModerator(moderator_model))
    return CompositeGuardrail(guardrails)


def main() -> None:
    try:
        settings = Settings()
    except ValidationError as error:
        missing = [
            str(item["loc"][0]).upper() for item in error.errors() if item["type"] == "missing"
        ]
        if missing:
            print("Заполни обязательные настройки в .env: " + ", ".join(missing))
        else:
            print(f"Проверь настройки в .env: {error}")
        return

    missing_settings = [
        name
        for name, value in {
            "API_KEY": settings.api_key,
            "BASE_URL": settings.base_url,
            "MODEL": settings.model,
        }.items()
        if not value
    ]
    if missing_settings:
        print("Заполни обязательные настройки в .env: " + ", ".join(missing_settings))
        return

    guardrail = _create_guardrail(settings)
    while True:
        setup = _create_game_setup(settings)
        setup_text = "\n".join(
            [setup.world, setup.story, setup.character.description, setup.character.goal]
        )
        if guardrail.check(setup_text).allowed:
            break
        print(BLOCK_MESSAGE + " Измени описание мира или героя.\n")

    game_state = GameState()
    try:
        memory = None
        if settings.embedding_model:
            embeddings = OpenAIEmbeddings(
                model=settings.embedding_model,
                api_key=settings.api_key,
                base_url=settings.embedding_base_url or settings.base_url,
            )
            memory = ChromaMemory(
                setup=setup,
                embeddings=embeddings,
                persist_directory=settings.memory_store_path,
                search_limit=settings.memory_search_limit,
            )

        agent = GameMasterAgent(
            settings,
            build_system_prompt(setup, vector_memory_enabled=memory is not None),
            game_state,
            memory,
        )
    except Exception as error:
        print(f"Не удалось настроить подключение к модели: {error}")
        return

    session = GameSession(agent, settings.history_limit, guardrail)
    print("Квест начался. Пиши 'выход' для выхода.\n")

    try:
        print("Мир: ", end="", flush=True)
        for chunk in session.start_stream():
            print(chunk, end="", flush=True)
        print("\n")
    except Exception as error:
        print(f"Не удалось подключиться к модели: {error}")
        return

    while True:
        try:
            action = input("Ты: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if action.lower() in {"выход", "quit", "exit"}:
            break
        if not action:
            print("Введи какое-нибудь действие.")
            continue

        try:
            print("\nМир: ", end="", flush=True)
            for chunk in session.send_action_stream(action):
                print(chunk, end="", flush=True)
            print("\n")
        except ContentBlockedError:
            print(f"\n{BLOCK_MESSAGE}\n")
            continue
        except Exception as error:
            print(f"\nОшибка: {error}\n")
            continue

    print("\nКвест завершён.")
