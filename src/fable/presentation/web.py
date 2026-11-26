"""HTTP/authentication and SSE adapters; game use cases live in GameService."""
from collections.abc import Awaitable, Callable, Generator
import json
import os
from pathlib import Path
from typing import cast

import anyio
from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictStr
from starlette.concurrency import run_in_threadpool
import uvicorn

from fable.application.auth import AuthService, AuthStore
from fable.application.game_service import (
    GameService, LoadedGame, GameError, GameNotFound, GameBusy, GameAlreadyStarted,
    GameNotStarted, Chunk, TurnCompleted, TurnBlocked, TurnFailed, TurnStream,
)
from fable.application.session import GameSession
from fable.bootstrap import (apply_setup_defaults, create_guardrail, create_session,
                             load_settings, validate_settings)
from fable.config import Settings
from fable.domain.models import GameSetup
from fable.domain.state import GameState
from fable.domain.user import User
from fable.infrastructure.auth_store import SqliteAuthStore
from fable.infrastructure.game_repository import JsonGameRepository
from fable.infrastructure.session_store import JsonSessionStore
from fable.presentation.auth import DEV_ORIGINS, OriginCheckMiddleware, configure_auth

SessionFactory = Callable[[Settings, GameSetup, GameState, dict | None], GameSession]


class CharacterBody(BaseModel):
    name: StrictStr
    role: StrictStr
    goal: StrictStr
    description: StrictStr
    genre: StrictStr


class CompanionBody(BaseModel):
    name: StrictStr
    role: StrictStr
    personality: StrictStr


class SetupBody(BaseModel):
    world: StrictStr
    story: StrictStr
    character: CharacterBody
    companions: list[CompanionBody] = Field(default_factory=list)


class ActionBody(BaseModel):
    action: StrictStr


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
    service = GameService(
        repository_factory=lambda owner: JsonGameRepository(user_store(owner) if owner is not None else root_store),
        session_factory=lambda setup, state, snapshot: factory(config, setup, state, snapshot),
        guardrail=create_guardrail(config),
        normalize_setup=lambda setup: apply_setup_defaults(setup, config),
    )
    app = FastAPI(title="Fable")
    auth = AuthService(auth_store if auth_store is not None else SqliteAuthStore(config.auth_db_path),
                       session_ttl_days=config.session_ttl_days,
                       allow_registration=config.allow_registration)
    current_user = configure_auth(app, config, auth)
    default_validation_handler = cast(Callable[[Request, RequestValidationError], Awaitable[Response]],
                                      app.exception_handlers[RequestValidationError])

    @app.exception_handler(RequestValidationError)
    async def invalid_body(request: Request, error: RequestValidationError):
        if any(tuple(item["loc"][:2]) == ("body", "companions") for item in error.errors()):
            return JSONResponse(status_code=422, content={
                "detail": "Спутники должны быть списком профилей со строковыми полями: имя, роль и характер.",
            })
        return await default_validation_handler(request, error)

    @app.exception_handler(GameError)
    async def game_error(request: Request, error: GameError):
        status = (404 if isinstance(error, GameNotFound) else
                  409 if isinstance(error, (GameBusy, GameAlreadyStarted, GameNotStarted)) else 422)
        return JSONResponse(status_code=status, content={"detail": str(error)})

    app.add_middleware(OriginCheckMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=DEV_ORIGINS, allow_credentials=True,
                       allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])

    @app.post("/api/games", status_code=201)
    def create_game(body: SetupBody, user: User = Depends(current_user)):
        game = service.create_game(user.id, GameSetup.from_dict(body.model_dump()))
        return _game(game.game.id, game)

    @app.get("/api/games")
    def list_games(user: User = Depends(current_user)):
        return [{key: item[key] for key in ("id", "title", "updated_at", "turns")}
                for item in service.list_games(user.id)]

    @app.get("/api/games/{game_id}")
    def get_game(game_id: str, user: User = Depends(current_user)):
        return _game(game_id, service.get_game(user.id, game_id))

    @app.delete("/api/games/{game_id}", status_code=204)
    def delete_game(game_id: str, user: User = Depends(current_user)):
        service.delete_game(user.id, game_id)
        return Response(status_code=204)

    def stream(turn: TurnStream) -> StreamingResponse:
        def generate():
            try:
                for item in turn:
                    if isinstance(item, Chunk):
                        yield _event("chunk", {"text": item.text})
                    elif isinstance(item, TurnCompleted):
                        verdict = item.consistency
                        state = dict(item.state)
                        state["location"] = state["location"] or ""
                        yield _event("done", {
                            "consistency": ({"consistent": verdict.consistent, "issues": list(verdict.issues)}
                                            if verdict is not None else None),
                            "state": state, "summary": item.summary, "events": item.events,
                        })
                    elif isinstance(item, TurnBlocked):
                        yield _event("blocked", {"message": item.message})
                    elif isinstance(item, TurnFailed):
                        yield _event("error", {"message": item.message})
            finally:
                turn.close()

        # Closing an unstarted generate() does not run its finally block.
        return GameStreamResponse(generate(), turn.close)

    @app.post("/api/games/{game_id}/start")
    def start_game(game_id: str, user: User = Depends(current_user)):
        return stream(service.start_stream(user.id, game_id))

    @app.post("/api/games/{game_id}/actions")
    def send_action(game_id: str, body: ActionBody, user: User = Depends(current_user)):
        return stream(service.play_turn_stream(user.id, game_id, body.action))

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
