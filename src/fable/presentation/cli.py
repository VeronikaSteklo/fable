from uuid import uuid4

from fable.application.guardrails import BLOCK_MESSAGE
from fable.application.persistence import build_game_record, parse_game_record
from fable.bootstrap import (apply_setup_defaults, create_guardrail, create_session,
                             load_settings, setup_text)
from fable.config import Settings
from fable.domain.models import Character, GameSetup
from fable.domain.safety import ContentBlockedError
from fable.domain.state import GameState
from fable.infrastructure.session_store import JsonSessionStore


def _create_character(settings: Settings) -> Character:
    print("=== Создание героя ===")
    print("Можно нажать Enter, чтобы использовать значения по умолчанию.\n")
    return Character(
        name=input("Имя персонажа: ").strip(),
        role=input("Роль: ").strip(),
        goal=input("Цель: ").strip(),
        description=input("Опиши героя (можно оставить пустым): ").strip(),
        genre=input("Жанр: ").strip(),
    )


def _create_game_setup(settings: Settings) -> GameSetup:
    print("=== Создание игры ===")
    world = input("Опиши мир: ").strip()
    story = input("Опиши завязку истории: ").strip()
    return apply_setup_defaults(
        GameSetup(world=world, story=story, character=_create_character(settings)), settings,
    )


def _choose_saved_game(store: JsonSessionStore) -> str | None:
    recent = store.list()[:5]
    if not recent:
        return None
    print("=== Сохранённые игры ===")
    for number, game in enumerate(recent, 1):
        print(f"{number}. {game['title']} — ходов: {game['turns']} ({game['updated_at']})")
    while True:
        answer = input("Продолжить игру (номер; Enter — новая игра): ").strip()
        if not answer:
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(recent):
            return recent[int(answer) - 1]["id"]
        print("Выбери номер из списка или нажми Enter.")


def main() -> None:
    try:
        settings = load_settings()
    except ValueError as error:
        print(error)
        return

    try:
        store = JsonSessionStore(settings.sessions_path)
        game_id = _choose_saved_game(store)
        created_at = None
        if game_id is not None:
            record = store.load(game_id)
            if record is None:
                raise ValueError("Сохранённая игра не найдена")
            parsed = parse_game_record(record)
            setup, game_state, created_at = parsed.setup, parsed.state, parsed.created_at
            session = create_session(settings, setup, game_state, parsed.session)
        else:
            guardrail = create_guardrail(settings)
            while True:
                setup = apply_setup_defaults(_create_game_setup(settings), settings)
                if guardrail.check(setup_text(setup)).allowed:
                    break
                print(BLOCK_MESSAGE + " Измени описание мира или героя.\n")
            game_id = uuid4().hex
            game_state = GameState()
            session = create_session(settings, setup, game_state)
            record = build_game_record(game_id, setup, game_state, session)
            store.save(game_id, record)
            created_at = record["created_at"]
    except (EOFError, KeyboardInterrupt):
        return
    except Exception as error:
        print(f"Не удалось подготовить игру: {error}")
        return

    def save():
        store.save(game_id, build_game_record(
            game_id, setup, game_state, session, created_at=created_at,
        ))

    print("Квест начался. Пиши 'выход' для выхода.\n")
    if session.started:
        last_reply = next(message["content"] for message in reversed(session.to_snapshot()["history"])
                          if message["role"] == "assistant")
        print(f"Мир: {last_reply}\n")
    else:
        try:
            print("Мир: ", end="", flush=True)
            for chunk in session.start_stream():
                print(chunk, end="", flush=True)
            save()
            print("\n")
        except Exception as error:
            print(f"Не удалось начать игру: {error}")
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
            save()
            print("\n")
        except ContentBlockedError:
            print(f"\n{BLOCK_MESSAGE}\n")
        except Exception as error:
            print(f"\nОшибка: {error}\n")
    print("\nКвест завершён.")
