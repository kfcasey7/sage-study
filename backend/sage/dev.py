"""Run the backend without the desktop window (for development and browser testing).

    python -m sage.dev            # serves the built frontend + API on http://127.0.0.1:8765
    cd frontend && npm run dev    # optional: Vite dev server with hot reload, proxying /api
    SAGE_FAKE_CLAUDE=1 python -m sage.dev   # demo mode: canned responses, no Claude Code calls
"""
from __future__ import annotations

import logging
import os

import uvicorn

from . import runtime
from .app import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    runtime.port = int(os.environ.get("SAGE_PORT", "8765"))
    if os.environ.get("SAGE_FAKE_CLAUDE") == "1":
        from .fake_claude import install_demo

        install_demo()
        logging.getLogger(__name__).warning("DEMO MODE: Claude calls are answered by canned responses.")
    uvicorn.run(create_app(), host="127.0.0.1", port=runtime.port, log_level="info")


if __name__ == "__main__":
    main()
