"""FastAPI application: API routers, error handling, local-only guard, and the built frontend."""
from __future__ import annotations

import html
import logging
import secrets as stdlib_secrets

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, desktop, llm_client, runtime
from .errors import AppError
from .routers import diagnostics, guide, sessions, sets, settings, updates, videos

log = logging.getLogger(__name__)

CLIENT_HEADER = "x-sage-client"
TOKEN_HEADER = "x-sage-token"
SIGNED_OUT_PAGE = (f"<!doctype html><title>{config.APP_NAME}</title><body style='font-family:system-ui;margin:3rem'>"
                   f"<h2>Please open {config.APP_NAME} from its shortcut</h2>"
                   "<p>This address only works from the app's own window, for your privacy.</p>")


def _forbidden(message: str, status: int = 403) -> JSONResponse:
    return JSONResponse({"error": {"code": "forbidden", "message": message}}, status_code=status)


def _token_ok(candidate: str | None) -> bool:
    return bool(candidate) and stdlib_secrets.compare_digest(candidate.encode(), runtime.token.encode())


def _guard(request: Request) -> JSONResponse | HTMLResponse | None:
    """Only this launch's own window may talk to the server.

      * Host: exactly 127.0.0.1:<port>, which stops DNS rebinding.
      * Origin: a browser's cross-site request is refused outright.
      * Token: other programs and web pages don't have this launch's secret. The launch URL swaps it for an
        HttpOnly, SameSite=Strict cookie, so it also covers images, downloads, and page loads.
      * Custom header on writes: a second, independent check against cross-site requests."""
    expected_host = f"127.0.0.1:{runtime.port}"
    host = (request.headers.get("host") or "").strip().lower()
    if runtime.auth_required:
        if host != expected_host:
            return _forbidden("Forbidden host.")
    elif host.rsplit(":", 1)[0].strip("[]") not in ("127.0.0.1", "localhost"):
        return _forbidden("Forbidden host.")

    origin = request.headers.get("origin")
    if runtime.auth_required and origin is not None and origin.lower() != f"http://{expected_host}":
        return _forbidden("Forbidden origin.")

    path = request.url.path
    if runtime.auth_required and path != "/launch":
        if not (_token_ok(request.cookies.get(runtime.cookie_name())) or _token_ok(request.headers.get(TOKEN_HEADER))):
            if path.startswith("/api/"):
                return _forbidden("Open the app from its shortcut.", status=401)
            return HTMLResponse(SIGNED_OUT_PAGE, status_code=401)

    if request.method not in ("GET", "HEAD", "OPTIONS") and path.startswith("/api/"):
        if request.headers.get(CLIENT_HEADER) != "1":
            return _forbidden("Missing client header.")
    return None


def create_app() -> FastAPI:
    db.init_db()
    llm_client.cleanup_tmp()  # remove CLI work folders left behind by a crash
    from .services import sources

    sources.cleanup_unattached()  # setup-screen files and links that never became a Study Set
    docs = {"docs_url": None, "redoc_url": None, "openapi_url": None} if runtime.auth_required         else {"docs_url": "/api/docs", "openapi_url": "/api/openapi.json"}
    app = FastAPI(title=config.APP_NAME, version=config.VERSION, **docs)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        refused = _guard(request)
        if refused is not None:
            return refused
        return await call_next(request)

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse({"error": exc.to_dict()}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        msg = f"Invalid request: {'.'.join(str(p) for p in first.get('loc', []))} {first.get('msg', '')}".strip()
        return JSONResponse({"error": AppError("bad_request", msg).to_dict()}, status_code=400)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception):
        log.exception("unhandled error", exc_info=exc)
        err = AppError("server_error", "Something went wrong in the app.", detail=repr(exc))
        return JSONResponse({"error": err.to_dict()}, status_code=500)

    app.include_router(settings.router)
    app.include_router(sessions.router)
    app.include_router(guide.router)
    app.include_router(sets.router)
    app.include_router(videos.router)
    app.include_router(diagnostics.router)
    app.include_router(updates.router)

    @app.get("/launch", include_in_schema=False)
    def launch(token: str = ""):
        if not _token_ok(token):
            return HTMLResponse(SIGNED_OUT_PAGE, status_code=401)
        response = RedirectResponse("/", status_code=303)  # the token leaves the address bar right away
        response.set_cookie(runtime.cookie_name(), runtime.token, httponly=True, samesite="strict", path="/")
        return response

    @app.get("/api/_ping")
    def ping() -> dict:
        return {"app": config.APP_ID, "version": config.VERSION}

    @app.post("/api/_focus")
    def focus() -> dict:
        return {"focused": desktop.focus(), "mode": runtime.window_mode}

    @app.post("/api/_heartbeat")
    def heartbeat() -> dict:
        desktop.heartbeat()
        return {"ok": True}

    @app.post("/api/_quit")
    def quit_app() -> dict:
        desktop.request_quit()
        return {"ok": True}

    dist = config.FRONTEND_DIST
    if (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            # The saved theme goes straight into the page, so the first paint is already in the right colors.
            theme = html.escape(str(db.get_settings().get("theme") or "light"), quote=True)
            page = (dist / "index.html").read_text(encoding="utf-8").replace("__SAGE_THEME__", theme)
            return HTMLResponse(page, headers={"Cache-Control": "no-store"})
    else:
        @app.get("/", include_in_schema=False)
        def no_frontend():
            return JSONResponse({"message": "The built UI is missing. Run: python scripts/build_frontend.py"})

    return app
