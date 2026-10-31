"""Local HTTP API and streamed game replies for the React client."""
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import threading
from uuid import uuid4
from typing import cast

import anyio
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StrictStr
from starlette.concurrency import run_in_threadpool
import uvicorn

from fable.application.auth import AuthService, AuthStore
from fable.application.guardrails import BLOCK_MESSAGE
from fable.application.persistence import build_game_record, parse_game_record
from fable.application.session import GameSession
from fable.bootstrap import (apply_setup_defaults, create_guardrail, create_session,
                             load_settings, setup_text, validate_settings)
from fable.config import Settings
from fable.domain.models import GameSetup
from fable.domain.safety import ContentBlockedError
from fable.domain.state import GameState
from fable.domain.user import User
from fable.infrastructure.auth_store import SqliteAuthStore
from fable.infrastructure.session_store import JsonSessionStore
from fable.presentation.auth import DEV_ORIGINS, OriginCheckMiddleware, configure_auth

logger = logging.getLogger(__name__)
SessionFactory = Callable[[Settings, GameSetup, GameState, dict | None], GameSession]


class CharacterBody(BaseModel):
    name: StrictStr
    role: StrictStr
    goal: StrictStr
    description: StrictStr
    genre: StrictStr


class SetupBody(BaseModel):
    world: StrictStr
    story: StrictStr
    character: CharacterBody


class ActionBody(BaseModel):
    action: StrictStr


@dataclass
class LoadedGame:
    setup: GameSetup
    state: GameState
    session: GameSession
    created_at: str
    lock: threading.Lock = field(default_factory=threading.Lock)


def _state(state: GameState) -> dict:
    # The client contract uses a string for an as-yet unknown location.
    result = state.to_dict()
    result["location"] = result["location"] or ""
    return result


def _game(game_id: str, game: LoadedGame) -> dict:
    return dict(id=game_id, setup=game.setup.to_dict(), started=game.session.started,
                entries=game.session.to_snapshot()["history"][1:], state=_state(game.state),
                summary=game.session.summary)


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class GameStreamResponse(StreamingResponse):
    """Close the synchronous generator even when ASGI cancels between chunks.

    StreamingResponse iterates sync bodies in a threadpool; its async wrapper
    alone does not guarantee closing the underlying Python generator.
    """
    def __init__(self, iterator: Generator[str, None, None], release: Callable[[], None]):
        super().__init__(iterator, media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
        })
        self._iterator = iterator
        self._release = release

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    await run_in_threadpool(self._iterator.close)
                finally:
                    self._release()


def create_app(settings: Settings | None = None, *, session_factory: SessionFactory | None = None,
               store: JsonSessionStore | None = None,
               auth_store: AuthStore | None = None,
               store_factory: Callable[[str], JsonSessionStore] | None = None) -> FastAPI:
    config = settings if settings is not None else load_settings()
    validate_settings(config)
    factory = session_factory if session_factory is not None else create_session
    root_store = store if store is not None else JsonSessionStore(config.sessions_path)
    user_store = store_factory if store_factory is not None else root_store.for_user
    guardrail = create_guardrail(config)
    loaded: dict[tuple[str, str], LoadedGame] = {}
    cache_lock = threading.Lock()
    app = FastAPI(title="Fable")
    auth = AuthService(auth_store if auth_store is not None else SqliteAuthStore(config.auth_db_path),
                       session_ttl_days=config.session_ttl_days,
                       allow_registration=config.allow_registration)
    current_user = configure_auth(app, config, auth)
    app.add_middleware(OriginCheckMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=DEV_ORIGINS, allow_credentials=True,
                       allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])

    def load(user: User, game_id: str) -> LoadedGame:
        key = (user.id, game_id)
        sessions = user_store(user.id)
        # Serialize restoration, otherwise two simultaneous first requests could
        # create separate sessions (and separate locks) for the same saved game.
        with cache_lock:
            if key not in loaded:
                try:
                    record = sessions.load(game_id)
                except ValueError:
                    raise HTTPException(404, "Игра не найдена") from None
                if record is None:
                    raise HTTPException(404, "Игра не найдена")
                parsed = parse_game_record(record)
                loaded[key] = LoadedGame(
                    parsed.setup, parsed.state,
                    factory(config, parsed.setup, parsed.state, parsed.session), parsed.created_at,
                )
            return loaded[key]

    def acquire(user: User, game_id: str, game: LoadedGame) -> None:
        with cache_lock:
            # A delete may have finished between load() and this operation.
            if loaded.get((user.id, game_id)) is not game:
                raise HTTPException(404, "Игра не найдена")
            if not game.lock.acquire(blocking=False):
                raise HTTPException(409, "Ответ для этой игры уже генерируется")

    @app.post("/api/games", status_code=201)
    def create_game(body: SetupBody, user: User = Depends(current_user)):
        sessions = user_store(user.id)
        setup = apply_setup_defaults(GameSetup.from_dict(body.model_dump()), config)
        if not guardrail.check(setup_text(setup)).allowed:
            raise HTTPException(422, BLOCK_MESSAGE + " Измени описание мира или героя.")
        state = GameState()
        session = factory(config, setup, state, None)
        game_id = uuid4().hex
        record = build_game_record(game_id, setup, state, session)
        sessions.save(game_id, record)
        with cache_lock:
            game = LoadedGame(setup, state, session, record["created_at"])
            loaded[(user.id, game_id)] = game
        return _game(game_id, game)

    @app.get("/api/games")
    def list_games(user: User = Depends(current_user)):
        sessions = user_store(user.id)
        return [{key: item[key] for key in ("id", "title", "updated_at", "turns")}
                for item in sessions.list()]

    @app.get("/api/games/{game_id}")
    def get_game(game_id: str, user: User = Depends(current_user)):
        return _game(game_id, load(user, game_id))

    @app.delete("/api/games/{game_id}", status_code=204)
    def delete_game(game_id: str, user: User = Depends(current_user)):
        sessions = user_store(user.id)
        game = load(user, game_id)
        acquire(user, game_id, game)
        try:
            with cache_lock:
                sessions.delete(game_id)
                loaded.pop((user.id, game_id), None)
        finally:
            game.lock.release()
        return Response(status_code=204)

    def stream(user: User, game_id: str, action: str | None = None) -> StreamingResponse:
        sessions = user_store(user.id)
        game = load(user, game_id)
        acquire(user, game_id, game)
        release_lock = threading.Lock()
        released = False

        def release():
            nonlocal released
            with release_lock:
                if not released:
                    released = True
                    game.lock.release()

        try:
            # Check under the same lock used for generation: two concurrent
            # starts must not both pass the started check.
            if action is None and game.session.started:
                raise HTTPException(409, "Игра уже началась")
            if action is not None and not game.session.started:
                raise HTTPException(409, "Сначала начни игру")
            before = game.session.to_snapshot()
            state_before = game.state.to_dict()
        except BaseException:
            release()
            raise

        def generate():
            successful = False
            reply = None
            try:
                reply = cast(Generator[str, None, None],
                             game.session.start_stream() if action is None
                             else game.session.send_action_stream(action))
                for chunk in reply:
                    yield _event("chunk", {"text": chunk})
                sessions.save(game_id, build_game_record(
                    game_id, game.setup, game.state, game.session, created_at=game.created_at,
                ))
                successful = True
                verdict = game.session.last_verdict
                yield _event("done", {
                    "consistency": ({"consistent": verdict.consistent, "issues": list(verdict.issues)}
                                    if verdict is not None else None),
                    "state": _state(game.state), "summary": game.session.summary,
                })
            except ContentBlockedError:
                yield _event("blocked", {"message": BLOCK_MESSAGE})
            except Exception:
                logger.exception("Не удалось завершить ход игры %s", game_id)
                yield _event("error", {"message": "Не удалось продолжить историю. Попробуй ещё раз."})
            finally:
                try:
                    if reply is not None:
                        reply.close()
                    if not successful:
                        # Tools can mutate state before the model fails. Restore
                        # both state and session, preserving the state reference.
                        restored = GameState.from_dict(state_before)
                        game.state.location = restored.location
                        game.state.inventory = restored.inventory
                        game.state.facts = restored.facts
                        game.session = factory(config, game.setup, game.state, before)
                finally:
                    release()

        return GameStreamResponse(generate(), release)

    @app.post("/api/games/{game_id}/start")
    def start_game(game_id: str, user: User = Depends(current_user)):
        return stream(user, game_id)

    @app.post("/api/games/{game_id}/actions")
    def send_action(game_id: str, body: ActionBody, user: User = Depends(current_user)):
        # Ownership takes precedence over action validation for hidden games.
        load(user, game_id)
        action = body.action.strip()
        if not action:
            raise HTTPException(422, "Введи какое-нибудь действие")
        return stream(user, game_id, action)

    dist = Path(os.environ.get(
        "FABLE_FRONTEND_DIST", Path(__file__).resolve().parents[3] / "frontend" / "dist",
    ))
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


def main() -> None:
    try:
        app = create_app()
        port = int(os.environ.get("FABLE_PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError("FABLE_PORT должен быть от 1 до 65535")
    except ValueError as error:
        print(error)
        return
    uvicorn.run(app, host=os.environ.get("FABLE_HOST", "127.0.0.1"), port=port)
