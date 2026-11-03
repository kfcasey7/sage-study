"""Create or remove the desktop shortcut and app-menu entry for the installed app (no terminal window).

    python -m sage.shortcuts create [--data-dir FOLDER]
    python -m sage.shortcuts remove

Windows: Sage Study.lnk on the Desktop and in the Start Menu, created via PowerShell + WScript.Shell.
macOS:   Sage Study.app in ~/Applications (a minimal bundle that starts the app), linked from the Desktop.
Linux:   sage-study.desktop on the Desktop and in ~/.local/share/applications.

SAGE_SHORTCUT_ROOT redirects all of them into one folder, for tests. Icons come from inside the package."""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from . import __version__, install_info
from .config import APP_NAME, ICON_DIR

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DESCRIPTION = "Quiz yourself and build study guides from your own material"


def test_root() -> Path | None:
    root = os.environ.get("SAGE_SHORTCUT_ROOT")
    return Path(root) if root else None


def gui_command() -> Path:
    """The launcher next to this environment's Python: no console window on Windows."""
    folder = Path(sys.executable).parent
    return folder / ("sage-study-gui.exe" if sys.platform == "win32" else "sage-study-gui")


def ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def windows_desktop() -> Path:
    # The Desktop may be redirected (e.g. to OneDrive); ask Windows instead of assuming ~/Desktop.
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
        capture_output=True, text=True, check=True, creationflags=NO_WINDOW,
    )
    return Path(out.stdout.strip())


def windows_start_menu() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def create_windows_lnk(path: Path, target: Path, args: str, icon: Path, description: str) -> None:
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut({lnk});"
        "$s.TargetPath = {target}; $s.Arguments = {args}; $s.WorkingDirectory = {cwd};"
        "$s.IconLocation = {icon}; $s.Description = {description};"
        "$s.WindowStyle = 1; $s.Save()"
    ).format(
        lnk=ps_quote(str(path)), target=ps_quote(str(target)), args=ps_quote(args), cwd=ps_quote(str(Path.home())),
        icon=ps_quote(f"{icon},0"), description=ps_quote(description),
    )
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], check=True, creationflags=NO_WINDOW)


def windows(remove: bool, app_args: list[str]) -> list[Path]:
    root = test_root()
    desktop = root / "Desktop" if root else windows_desktop()
    menu = root / "StartMenu" if root else windows_start_menu()
    paths = [desktop / f"{APP_NAME}.lnk", menu / f"{APP_NAME}.lnk"]
    uninstall = menu / f"Uninstall {APP_NAME}.lnk"
    if remove:
        for p in (*paths, uninstall):
            p.unlink(missing_ok=True)
        return [*paths, uninstall]
    args = subprocess.list2cmdline(app_args)
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        create_windows_lnk(p, gui_command(), args, ICON_DIR / "icon.ico", DESCRIPTION)
    info = install_info.load()
    if info["kind"] == "installer":
        script = Path(info["root"]) / "uninstall.ps1"
        create_windows_lnk(uninstall, Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe",
                           f'-NoProfile -ExecutionPolicy Bypass -File "{script}"', ICON_DIR / "icon.ico", f"Remove {APP_NAME}")
        paths.append(uninstall)
    return paths


def macos(remove: bool, app_args: list[str]) -> list[Path]:
    root = test_root()
    home = root or Path.home()
    app = home / "Applications" / f"{APP_NAME}.app"
    link = home / "Desktop" / f"{APP_NAME}.app"
    if link.is_symlink() or link.exists():
        link.unlink() if link.is_symlink() else shutil.rmtree(link)
    if app.exists():
        shutil.rmtree(app)
    if remove:
        return [app, link]
    macos_dir = app / "Contents" / "MacOS"
    resources = app / "Contents" / "Resources"
    macos_dir.mkdir(parents=True)
    resources.mkdir(parents=True)
    shutil.copy(ICON_DIR / "icon.icns", resources / "icon.icns")
    (app / "Contents" / "Info.plist").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>{APP_NAME}</string>
  <key>CFBundleDisplayName</key><string>{APP_NAME}</string>
  <key>CFBundleIdentifier</key><string>io.github.kfcasey7.sagestudy</string>
  <key>CFBundleVersion</key><string>{__version__}</string>
  <key>CFBundleShortVersionString</key><string>{__version__}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>SageStudy</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
""")
    exe = macos_dir / "SageStudy"
    quoted = " ".join(f'"{a}"' for a in app_args)
    exe.write_text(f'#!/bin/bash\nexec "{gui_command()}" {quoted} >/dev/null 2>&1\n')
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(app)
    return [app, link]


def linux(remove: bool, app_args: list[str]) -> list[Path]:
    root = test_root()
    if root:
        desktop_dir, menu_dir = root / "Desktop", root / "applications"
    else:
        named = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip() if shutil.which("xdg-user-dir") else ""
        desktop_dir, menu_dir = Path(named or Path.home() / "Desktop"), Path.home() / ".local" / "share" / "applications"
    paths = [desktop_dir / "sage-study.desktop", menu_dir / "sage-study.desktop"]
    quoted = " ".join(f'"{a}"' for a in app_args)
    entry = f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Comment={DESCRIPTION}
Exec="{gui_command()}" {quoted}
Icon={ICON_DIR / 'icon.png'}
Terminal=false
Categories=Education;
StartupWMClass={APP_NAME}
"""
    for p in paths:
        if remove:
            p.unlink(missing_ok=True)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(entry)
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if shutil.which("gio") and p.parent == desktop_dir:
            subprocess.run(["gio", "set", str(p), "metadata::trusted", "true"], capture_output=True)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["create", "remove"])
    parser.add_argument("--data-dir", help="have the shortcut start the app with this data folder")
    args = parser.parse_args()
    remove = args.action == "remove"
    if not remove and not gui_command().exists():
        print(f"Missing {gui_command()}. Install the app first.")
        return 1
    app_args = ["--data-dir", args.data_dir] if args.data_dir else []
    make = windows if sys.platform == "win32" else macos if sys.platform == "darwin" else linux
    for p in make(remove, app_args):
        print(("Removed " if remove else "Created ") + str(p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
