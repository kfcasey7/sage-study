"""Desktop entry point: start the API server in a background thread and open the native window.

Only one instance runs at a time. The first instance holds an OS-level lock on `instance.lock`
and records its port in `instance.json`; a second launch finds the lock taken, asks the running
instance to bring its window to the front, and exits."""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import IO

from . import config, desktop, runtime

log = logging.getLogger("sage")
INSTANCE_FILE = config.DATA_DIR / "instance.json"


# --- Logging (pythonw has no console: stdout/stderr are None) ---------------------------

def setup_logging() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(config.LOG_FILE, maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stdout is None or sys.stderr is None:
        stream = open(config.LOG_FILE, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives for the process
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
        try:
            # Point the OS-level stderr at the log too, so native/.NET crash output isn't lost.
            os.dup2(stream.fileno(), 2)
        except OSError:
            pass
    import faulthandler

    faulthandler.enable(file=sys.stderr)


# --- Single instance ----------------------------------------------------------------------

class InstanceLock:
    """Exclusive, process-lifetime lock. The OS releases it if the process dies."""

    def __init__(self, path: Path):
        self.path = path
        self.handle: IO[str] | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+")  # noqa: SIM115
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        return True

    def release(self) -> None:
        if self.handle:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    self.handle.seek(0)
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            self.handle.close()
            self.handle = None


def focus_existing(timeout: float = 15.0) -> bool:
    """Ask the running instance to show its window. Retries while it may still be starting."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            info = json.loads(INSTANCE_FILE.read_text())
            port = info["port"]
            if sys.platform == "win32":
                # We were just launched by the user, so we hold foreground rights; pass them on.
                import ctypes

                ctypes.windll.user32.AllowSetForegroundWindow(int(info["pid"]))
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/_ping", timeout=1) as r:
                if json.loads(r.read()).get("app") != config.APP_ID:
                    raise OSError("port is not Sage Study")
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/_focus", method="POST", data=b"", headers={"x-sage-client": "1"},
            )
            urllib.request.urlopen(req, timeout=2).close()
            return True
        except (OSError, ValueError, KeyError):
            time.sleep(0.4)
    return False


def pick_port() -> int:
    for port in (config.PREFERRED_PORT, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("no free port")


# --- Server --------------------------------------------------------------------------------

def start_server(port: int):
    import uvicorn

    from .app import create_app

    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_config=None, access_log=False))
    thread = threading.Thread(target=server.run, name="sage-api", daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started:
        if not thread.is_alive() or time.time() > deadline:
            raise RuntimeError("The local server failed to start. See the log file for details.")
        time.sleep(0.05)
    return server, thread


# --- Window --------------------------------------------------------------------------------

def set_windows_app_id() -> None:
    """Group the window under its own taskbar entry (with our icon) instead of python.exe's."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SageStudy.Desktop")
        except Exception:  # noqa: BLE001
            pass


def initial_geometry(webview) -> tuple[int, int, int | None, int | None]:
    """Size and position: 1280x860 when it fits, otherwise ~92% x 86% of the screen (high-DPI laptops
    have small logical screens), centered with room left for the taskbar."""
    width, height, x, y = 1280, 860, None, None
    try:
        screen = webview.screens[0]
        width = max(900, min(width, int(screen.width * 0.92)))
        height = max(600, min(height, int(screen.height * 0.86)))
        taskbar = 48
        x = screen.x + max(0, (screen.width - width) // 2)
        y = screen.y + max(0, (screen.height - taskbar - height) // 2)
    except Exception:  # noqa: BLE001 - screen info unavailable on some backends
        pass
    return width, height, x, y


def show_fatal(message: str) -> None:
    log.error(message)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, config.APP_NAME, 0x10)
            return
        except Exception:  # noqa: BLE001
            pass
    print(message, file=sys.stderr)


def main() -> int:
    setup_logging()
    lock = InstanceLock(config.LOCK_FILE)
    if not lock.acquire():
        log.info("another instance is running; focusing it")
        return 0 if focus_existing() else 1

    server = None
    try:
        import webview

        port = pick_port()
        runtime.port = port
        server, thread = start_server(port)
        INSTANCE_FILE.write_text(json.dumps({"pid": os.getpid(), "port": port}))
        log.info("Sage Study %s running on %s", config.VERSION, runtime.server_url())

        set_windows_app_id()
        width, height, x, y = initial_geometry(webview)
        window = webview.create_window(
            config.APP_NAME,
            runtime.server_url() + "/",
            width=width,
            height=height,
            x=x,
            y=y,
            min_size=(900, 600),
            background_color="#F4F6F1",
            text_select=True,
        )
        desktop.window = window
        if sys.platform == "win32":
            # A launch from a hidden process can start the window minimized; always open it normally.
            window.events.shown += lambda: desktop.restore_win32()
        # WinForms (Windows) only accepts .ico; GTK/Qt take a .png. A wrong format crashes the UI thread.
        icon = config.ICON_DIR / ("icon.ico" if sys.platform == "win32" else "icon.png")
        webview.start(
            private_mode=False,  # keep localStorage (theme, form preferences) between runs
            storage_path=str(config.DATA_DIR / "webview"),
            icon=str(icon) if icon.exists() else None,
        )
        return 0
    except Exception as e:  # noqa: BLE001
        log.exception("fatal error")
        show_fatal(f"Sage Study couldn't start:\n\n{e}\n\nLog file: {config.LOG_FILE}")
        return 1
    finally:
        desktop.window = None
        if server is not None:
            server.should_exit = True
        try:
            INSTANCE_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
