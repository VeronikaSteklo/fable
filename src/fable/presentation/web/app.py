"""HTTP/authentication and SSE adapters; game use cases live in GameService."""
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import cast

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from fable.application.auth.service import AuthService, AuthStore
from fable.application.ports import PersistenceConflict
from fable.application.game.service import (
    GameService, LoadedGame, GameError, GameNotFound, GameBusy, GameAlreadyStarted,
    GameNotStarted, Chunk, TurnCompleted, TurnBlocked, TurnFailed, TurnStream,
)
from fable.application.game.session import GameSession
from fable.bootstrap import (apply_setup_defaults, create_guardrail, create_session,
                             load_settings, validate_settings, create_backend_resources)
from fable.config import Settings
from fable.domain.game.setup import GameSetup
from fable.domain.game.state import GameState
from fable.domain.users.user import User
from fable.infrastructure.persistence.session_store import JsonSessionStore
from fable.presentation.web.auth import DEV_ORIGINS, OriginCheckMiddleware, configure_auth
from fable.presentation.web.schemas import SetupBody, ActionBody
from fable.presentation.web.sse import GameStreamResponse, _event

SessionFactory = Callable[[Settings, GameSetup, GameState, dict | None], GameSession]


def _state(state: GameState) -> dict:
    # The client contract uses a string for an as-yet unknown location.
    result = state.to_dict()
    result["location"] = result["location"] or ""
    return result


def _game(game_id: str, game: LoadedGame) -> dict:
    return dict(id=game_id, setup=game.setup.to_dict(), started=game.session.started,
                entries=game.session.to_snapshot()["history"][1:], state=_state(game.state),
                summary=game.session.summary, usage_total=game.session.usage_total)


def create_app(settings: Settings | None = None, *, session_factory: SessionFactory | None = None,
               store: JsonSessionStore | None = None,
               auth_store: AuthStore | None = None,
               store_factory: Callable[[str], JsonSessionStore] | None = None) -> FastAPI:
    config = settings if settings is not None else load_settings()
    validate_settings(config)
    factory = session_factory if session_factory is not None else create_session
    resources = create_backend_resources(config, store=store, store_factory=store_factory, auth_store=auth_store)
    service = GameService(
        repository_factory=resources.repositories,
        session_factory=lambda setup, state, snapshot: factory(config, setup, state, snapshot),
        guardrail=create_guardrail(config),
        normalize_setup=lambda setup: apply_setup_defaults(setup, config),
        lock_manager=resources.locks,
        turn_lock_ttl_seconds=config.turn_lock_ttl_seconds,
        reload_on_read=bool(config.database_url or config.redis_url),
    )

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            resources.close()

    app = FastAPI(title="Fable", lifespan=lifespan)
    auth = AuthService(resources.auth_store, session_ttl_days=config.session_ttl_days,
                       allow_registration=config.allow_registration, rate_limiter=resources.rate_limiter)
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

    @app.exception_handler(PersistenceConflict)
    async def persistence_conflict(request: Request, error: PersistenceConflict):
        return JSONResponse(status_code=409, content={"detail": str(error)})

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
                            "state": state, "summary": item.summary, "events": item.events, "usage": item.usage,
                        })
                    elif isinstance(item, TurnBlocked):
                        yield _event("blocked", {"message": item.message})
                    elif isinstance(item, TurnFailed):
                        payload: dict = {"message": item.message}
                        if item.status_code == 409:
                            payload["status_code"] = 409
                        yield _event("error", payload)
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
        "FABLE_FRONTEND_DIST", Path(__file__).resolve().parents[4] / "frontend" / "dist",
    ))
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


def main() -> None:
    try:
        config = load_settings()
        workers = int(os.environ.get("FABLE_WORKERS", "1"))
        if workers < 1:
            raise ValueError("FABLE_WORKERS должен быть положительным числом")
        if workers > 1 and not (config.database_url and config.redis_url):
            raise ValueError("Для FABLE_WORKERS > 1 нужны DATABASE_URL и REDIS_URL (PostgreSQL и Redis)")
        port = int(os.environ.get("FABLE_PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError("FABLE_PORT должен быть от 1 до 65535")
    except ValueError as error:
        print(error)
        return
    host = os.environ.get("FABLE_HOST", "127.0.0.1")
    if workers > 1:
        uvicorn.run('fable.presentation.web.app:create_app', factory=True, workers=workers, host=host, port=port)
    else:
        uvicorn.run(create_app(config), host=host, port=port)
