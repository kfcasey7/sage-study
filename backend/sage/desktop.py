"""Bridge to the native pywebview window (when running as a desktop app). Every function degrades
gracefully when there is no window, e.g. when the backend runs on its own for development."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from platformdirs import user_downloads_dir

log = logging.getLogger(__name__)

window: Any = None  # set by main.py once the window exists
_exported: set[str] = set()

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _own_hwnd() -> int | None:
    """Handle of this process's visible top-level window titled like the app (Windows only)."""
    import ctypes
    from ctypes import wintypes

    from . import config

    user32 = ctypes.windll.user32
    pid = os.getpid()
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value == config.APP_NAME:
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(callback, 0)
    return found[0] if found else None


def restore_win32() -> bool:
    """Un-minimize and raise the window with Win32 calls. pywebview's restore() relies on the
    WinForms WindowState, which can miss a window that was shown minimized."""
    import ctypes

    hwnd = _own_hwnd()
    if not hwnd:
        return False
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9 if user32.IsIconic(hwnd) else 5)  # SW_RESTORE / SW_SHOW
    user32.SetForegroundWindow(hwnd)
    return True


def focus() -> bool:
    if window is None:
        return False
    if sys.platform == "win32":
        try:
            if restore_win32():
                return True
        except Exception:  # noqa: BLE001 - fall back to pywebview
            log.exception("win32 focus failed")
    try:
        window.restore()
        window.show()
        # Toggling on_top is the portable way to raise a window above others.
        window.on_top = True
        window.on_top = False
        return True
    except Exception:  # noqa: BLE001
        log.exception("could not focus window")
        return False


def choose_save_path(default_name: str, file_type: str) -> Path | None:
    """Ask the user where to save. Returns None if they cancel. Without a window, saves to Downloads."""
    if window is not None:
        import webview

        result = window.create_file_dialog(
            webview.FileDialog.SAVE,
            directory=user_downloads_dir(),
            save_filename=default_name,
            file_types=(file_type,),
        )
        if not result:
            return None
        path = result[0] if isinstance(result, (list, tuple)) else result
        return Path(path)
    target = Path(user_downloads_dir()) / default_name
    stem, suffix, n = target.stem, target.suffix, 1
    while target.exists():
        target = target.with_name(f"{stem} ({n}){suffix}")
        n += 1
    return target


def remember_export(path: Path) -> None:
    _exported.add(str(path.resolve()))


def reveal(path_str: str) -> bool:
    """Show an exported file in the OS file manager. Only paths this app exported are allowed."""
    path = Path(path_str).resolve()
    if str(path) not in _exported or not path.exists():
        return False
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)], creationflags=NO_WINDOW)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])
    return True


def open_file(path_str: str) -> bool:
    path = Path(path_str).resolve()
    if str(path) not in _exported or not path.exists():
        return False
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
    return True
