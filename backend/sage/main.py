"""Desktop entry point: start the API server in a background thread and open the native window, or the
default browser when no native window can start.

Only one instance runs at a time. The first instance holds an OS-level lock on `instance.lock` and records its
port and launch token in `instance.json`; a second launch finds the lock taken, asks the running instance to
bring its window to the front, and exits."""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
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


def write_instance_file() -> None:
    """Holds this launch's token, so only this user's account may read it."""
    INSTANCE_FILE.unlink(missing_ok=True)
    fd = os.open(INSTANCE_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"pid": os.getpid(), "port": runtime.port, "token": runtime.token}, f)


def focus_existing(timeout: float = 15.0) -> bool:
    """Ask the running instance to show its window. Retries while it may still be starting."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            info = json.loads(INSTANCE_FILE.read_text())
            port, token = info["port"], info["token"]
            headers = {"x-sage-client": "1", "x-sage-token": token}
            if sys.platform == "win32":
                # We were just launched by the user, so we hold foreground rights; pass them on.
                import ctypes

                ctypes.windll.user32.AllowSetForegroundWindow(int(info["pid"]))
            ping = urllib.request.Request(f"http://127.0.0.1:{port}/api/_ping", headers=headers)
            with urllib.request.urlopen(ping, timeout=1) as r:
                if json.loads(r.read()).get("app") != config.APP_ID:
                    raise OSError("port is not Sage Study")
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/_focus", method="POST", data=b"", headers=headers)
            with urllib.request.urlopen(req, timeout=2) as r:
                result = json.loads(r.read())
            if not result.get("focused"):  # running in a browser tab: all we can do is open another one
                webbrowser.open(f"http://127.0.0.1:{port}/launch?token={token}")
            return True
        except (OSError, ValueError, KeyError):
            time.sleep(0.4)
    return False


# --- Server --------------------------------------------------------------------------------

def bind_free_port() -> socket.socket:
    """127.0.0.1 only, on a port the OS picks. The socket stays open and goes straight to the server, so
    nothing else can take the port in between."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.set_inheritable(True)
    return sock


def start_server(sock: socket.socket):
    import uvicorn

    from .app import create_app

    runtime.port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(), log_config=None, access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, name="sage-api", daemon=True)
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
    elif sys.platform == "darwin":
        try:
            quoted = message.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(["osascript", "-e", f'display alert "{config.APP_NAME}" message "{quoted}" as critical'], timeout=120, check=True)
            return
        except (OSError, subprocess.SubprocessError):
            pass
    print(message, file=sys.stderr)


def run_window() -> None:
    """Open the native window and block until it closes. Raises if this computer can't show one."""
    if sys.platform not in ("win32", "darwin") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise RuntimeError("no graphical display was found")
    import webview

    set_windows_app_id()
    width, height, x, y = initial_geometry(webview)
    window = webview.create_window(
        config.APP_NAME,
        runtime.launch_url(),
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
        private_mode=False,  # keep the window's own state between runs
        storage_path=str(config.DATA_DIR / "webview"),
        icon=str(icon) if icon.exists() else None,
    )


def run_browser(reason: str) -> None:
    """No native window: use the default browser, and keep running until the tab has been gone for a while."""
    runtime.window_mode = "browser"
    runtime.fallback_reason = reason
    runtime.last_heartbeat = time.monotonic()
    log.warning("opening in the browser: %s", reason)
    if not webbrowser.open(runtime.launch_url()):
        show_fatal(f"{config.APP_NAME} couldn't open a window or your browser.\n\nOpen this address in a browser to use it:\n"
                   f"{runtime.launch_url()}")
    while not runtime.stop_requested and time.monotonic() - runtime.last_heartbeat < config.BROWSER_IDLE_EXIT_SECONDS:
        time.sleep(1)


def main(force_browser: bool = False) -> int:
    setup_logging()
    lock = InstanceLock(config.LOCK_FILE)
    if not lock.acquire():
        log.info("another instance is running; focusing it")
        return 0 if focus_existing() else 1

    server = None
    try:
        server, thread = start_server(bind_free_port())
        write_instance_file()
        log.info("%s %s running on %s", config.APP_NAME, config.VERSION, runtime.server_url())
        if force_browser:
            run_browser("you asked for the browser version")
        else:
            try:
                run_window()
            except Exception as e:  # noqa: BLE001 - missing GTK/Qt/WebView2, or no display at all
                log.exception("the native window couldn't start")
                desktop.window = None
                run_browser(str(e) or type(e).__name__)
        return 0
    except Exception as e:  # noqa: BLE001
        log.exception("fatal error")
        show_fatal(f"{config.APP_NAME} couldn't start:\n\n{getattr(e, 'message', e)}\n\nLog file: {config.LOG_FILE}")
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
