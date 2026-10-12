"""FastAPI application: API routers, error handling, local-only guard, and the built frontend."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, desktop
from .errors import AppError
from .routers import guide, sessions, settings

log = logging.getLogger(__name__)

CLIENT_HEADER = "x-sage-client"
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


def create_app() -> FastAPI:
    db.init_db()
    app = FastAPI(title=config.APP_NAME, version=config.VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Reject DNS-rebinding requests (wrong Host) and cross-site writes from web pages: browsers
        # can't attach a custom header cross-origin without a CORS preflight, which we never allow.
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"error": {"code": "forbidden", "message": "Forbidden host."}}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/"):
            if request.headers.get(CLIENT_HEADER) != "1":
                return JSONResponse({"error": {"code": "forbidden", "message": "Missing client header."}}, status_code=403)
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

    @app.get("/api/_ping")
    def ping() -> dict:
        return {"app": config.APP_ID, "version": config.VERSION}

    @app.post("/api/_focus")
    def focus() -> dict:
        return {"focused": desktop.focus()}

    dist = config.FRONTEND_DIST
    if (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-store"})
    else:
        @app.get("/", include_in_schema=False)
        def no_frontend():
            return JSONResponse({"message": "Frontend not built. Run: cd frontend && npm run build"})

    return app
