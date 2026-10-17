from pydantic import ValidationError

from fable.application.prompts import build_system_prompt
from fable.application.session import GameSession
from fable.config import Settings
from fable.domain.models import Character, GameSetup
from fable.infrastructure.master_agent import GameMasterAgent


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

    setup = _create_game_setup(settings)
    try:
        agent = GameMasterAgent(settings, build_system_prompt(setup))
    except Exception as error:
        print(f"Не удалось настроить подключение к модели: {error}")
        return

    session = GameSession(agent, settings.history_limit)
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
        except Exception as error:
            print(f"\nОшибка: {error}\n")
            continue

    print("\nКвест завершён.")
