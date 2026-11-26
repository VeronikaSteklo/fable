from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from fable.application.safety.guardrails import BLOCK_MESSAGE
from fable.application.ports import GameRepository, StoredGame
from fable.bootstrap import (apply_setup_defaults, create_guardrail, create_session,
                             load_settings, setup_text)
from fable.config import Settings
from fable.domain.companions.companion import Companion, InvalidSetupError
from fable.domain.game.game import Game
from fable.domain.game.setup import Character, GameSetup
from fable.domain.safety.safety import ContentBlockedError
from fable.infrastructure.persistence.game_repository import JsonGameRepository
from fable.infrastructure.persistence.session_store import JsonSessionStore


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
    setup = apply_setup_defaults(
        GameSetup(world=world, story=story, character=_create_character(settings)), settings,
    )
    for _ in range(3):
        while True:
            answer = input("Добавить спутника? (д/н): ").strip().casefold()
            if answer in {"", "н", "нет"}:
                return setup
            if answer in {"д", "да"}:
                break
            print("Ответь «д» или «н».")
        while True:
            companion = Companion(
                name=input("Имя спутника: ").strip(),
                role=input("Роль спутника: ").strip(),
                personality=input("Характер спутника: ").strip(),
            )
            candidate = replace(setup, companions=(*setup.companions, companion))
            try:
                candidate.validate()
            except InvalidSetupError as error:
                print(error)
                continue
            setup = candidate
            break
    return setup


def _choose_saved_game(repository: GameRepository) -> str | None:
    recent = repository.list_summaries()[:5]
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
        repository = JsonGameRepository(JsonSessionStore(settings.sessions_path))
        game_id = _choose_saved_game(repository)
        if game_id is not None:
            stored = repository.get(game_id)
            if stored is None:
                raise ValueError("Сохранённая игра не найдена")
            game = stored.game
            setup, game_state = game.setup, game.state
            session = create_session(settings, setup, game_state, stored.session)
        else:
            guardrail = create_guardrail(settings)
            while True:
                setup = apply_setup_defaults(_create_game_setup(settings), settings)
                if guardrail.check(setup_text(setup)).allowed:
                    break
                print(BLOCK_MESSAGE + " Измени описание мира или героя.\n")
            game_id = uuid4().hex
            game = Game.create(game_id, None, setup, datetime.now(timezone.utc).isoformat())
            game_state = game.state
            session = create_session(settings, setup, game_state)
            repository.add(StoredGame(game, session.to_snapshot()))
    except (EOFError, KeyboardInterrupt):
        return
    except Exception as error:
        print(f"Не удалось подготовить игру: {error}")
        return

    def save():
        session.attach_events([event.to_dict() for event in game.pull_events()])
        game.updated_at = datetime.now(timezone.utc).isoformat()
        repository.save(StoredGame(game, session.to_snapshot()))

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
