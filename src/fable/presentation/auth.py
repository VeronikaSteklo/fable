"""Cookie authentication HTTP adapter."""
from fastapi import Depends, FastAPI, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StrictStr
from starlette.types import ASGIApp, Receive, Scope, Send

from fable.application.auth import AuthError, AuthService
from fable.config import Settings
from fable.domain.user import User

COOKIE_NAME = "fable_session"
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


class OriginCheckMiddleware:
    """Reject cross-origin writes without wrapping/buffering SSE responses."""
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (scope["type"] == "http" and scope["method"] in {"POST", "DELETE"}
                and scope["path"].startswith("/api/")):
            request = Request(scope)
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.url.netloc}"
            if origin is not None and origin not in [expected, *DEV_ORIGINS]:
                response = JSONResponse(status_code=403, content={"detail": "Недопустимый источник запроса"})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class CredentialsBody(BaseModel):
    username: StrictStr
    password: StrictStr


def configure_auth(app: FastAPI, config: Settings, auth: AuthService):
    @app.exception_handler(AuthError)
    async def auth_error(request: Request, error: AuthError):
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail})

    @app.exception_handler(RequestValidationError)
    async def invalid_body(request: Request, error: RequestValidationError):
        if request.url.path.startswith("/api/auth/"):
            return JSONResponse(status_code=422, content={
                "detail": "Укажи имя пользователя и пароль строками в JSON",
            })
        return await request_validation_exception_handler(request, error)

    def current_user(request: Request) -> User:
        return auth.current_user(request.cookies.get(COOKIE_NAME))

    def signed_in(response: Response, result: tuple[User, str]) -> dict:
        user, token = result
        response.set_cookie(COOKIE_NAME, token, max_age=config.session_ttl_days * 86400,
                            httponly=True, secure=config.cookie_secure, samesite="lax", path="/")
        return {"user": {"id": user.id, "username": user.username}}

    @app.post("/api/auth/register", status_code=201)
    def register(body: CredentialsBody, response: Response):
        return signed_in(response, auth.register(body.username, body.password))

    @app.post("/api/auth/login")
    def login(body: CredentialsBody, response: Response):
        return signed_in(response, auth.login(body.username, body.password))

    @app.post("/api/auth/logout", status_code=204)
    def logout(request: Request):
        auth.logout(request.cookies.get(COOKIE_NAME))
        response = Response(status_code=204)
        response.delete_cookie(COOKIE_NAME, path="/", httponly=True,
                               secure=config.cookie_secure, samesite="lax")
        return response

    @app.get("/api/auth/me")
    def me(user: User = Depends(current_user)):
        return {"user": {"id": user.id, "username": user.username}}

    return current_user
