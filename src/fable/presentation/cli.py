from fable.application.session import GameSession
from fable.config import Settings
from fable.domain.models import Character, GameSetup
from fable.infrastructure.llm_client import LLMClient


def _create_character() -> Character:
    print("=== Создание героя ===")
    print("Можно нажать Enter, чтобы использовать значения по умолчанию.\n")

    name = input("Имя персонажа: ").strip() or "Безымянный герой"
    role = input("Роль: ").strip() or "странник"
    goal = input("Цель: ").strip() or "раскрыть тайну"
    description = input("Опиши героя (можно оставить пустым): ").strip()
    genre = input("Жанр: ").strip() or "фэнтези"

    return Character(
        name=name,
        role=role,
        goal=goal,
        description=description,
        genre=genre,
    )


def _create_game_setup() -> GameSetup:
    print("=== Создание игры ===")
    world = input("Опиши мир: ").strip()
    if not world:
        world = "Фэнтезийный мир, в котором древняя магия постепенно возвращается."

    story = input("Опиши завязку истории: ").strip()
    if not story:
        story = "Герой оказывается перед загадкой, которая может изменить его жизнь."

    return GameSetup(world=world, story=story, character=_create_character())


def main() -> None:
    try:
        settings = Settings.from_environment()
    except ValueError as error:
        print(error)
        return

    try:
        client = LLMClient(
            base_url=settings.base_url,
            model=settings.model,
            api_key=settings.api_key,
        )
    except Exception as error:
        print(f"Не удалось настроить подключение к модели: {error}")
        return

    setup = _create_game_setup()
    session = GameSession(setup, client)
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
