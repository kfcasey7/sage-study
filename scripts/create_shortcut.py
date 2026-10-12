"""Create a desktop shortcut that launches Sage Study with no terminal window.

    python scripts/create_shortcut.py            # create / refresh the shortcut
    python scripts/create_shortcut.py --remove   # delete it

Windows: Sage Study.lnk on the Desktop (and Start Menu), created via PowerShell + WScript.Shell, running
         .venv\\Scripts\\pythonw.exe launcher.pyw.
macOS:   Sage Study.app on the Desktop: a minimal bundle whose executable starts the venv Python.
Linux:   sage-study.desktop on the Desktop and in ~/.local/share/applications.
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "Sage Study"
ICON_DIR = ROOT / "assets" / "icon"
LAUNCHER = ROOT / "launcher.pyw"


def venv_python(windowed: bool) -> Path:
    if sys.platform == "win32":
        return ROOT / ".venv" / "Scripts" / ("pythonw.exe" if windowed else "python.exe")
    return ROOT / ".venv" / "bin" / "python"


def ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def windows_desktop() -> Path:
    # The Desktop may be redirected (e.g. to OneDrive); ask Windows instead of assuming ~/Desktop.
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
        capture_output=True, text=True, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return Path(out.stdout.strip())


def windows_start_menu() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def create_windows_lnk(path: Path) -> None:
    target = venv_python(windowed=True)
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut({lnk});"
        "$s.TargetPath = {target}; $s.Arguments = {args}; $s.WorkingDirectory = {cwd};"
        "$s.IconLocation = {icon}; $s.Description = 'Quiz yourself and build study guides with Claude';"
        "$s.WindowStyle = 1; $s.Save()"
    ).format(
        lnk=ps_quote(str(path)), target=ps_quote(str(target)), args=ps_quote(f'"{LAUNCHER}"'),
        cwd=ps_quote(str(ROOT)), icon=ps_quote(f"{ICON_DIR / 'icon.ico'},0"),
    )
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def windows(remove: bool) -> list[Path]:
    paths = [windows_desktop() / f"{APP_NAME}.lnk", windows_start_menu() / f"{APP_NAME}.lnk"]
    for p in paths:
        if remove:
            p.unlink(missing_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            create_windows_lnk(p)
    return paths


def macos(remove: bool) -> list[Path]:
    app = Path.home() / "Desktop" / f"{APP_NAME}.app"
    if app.exists():
        shutil.rmtree(app)
    if remove:
        return [app]
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
  <key>CFBundleIdentifier</key><string>com.sagestudy.desktop</string>
  <key>CFBundleVersion</key><string>1.0.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>SageStudy</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
""")
    exe = macos_dir / "SageStudy"
    exe.write_text(f"""#!/bin/bash
cd "{ROOT}"
exec "{venv_python(False)}" "{LAUNCHER}" >/dev/null 2>&1
""")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return [app]


def linux(remove: bool) -> list[Path]:
    desktop_dir = Path(subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip() or Path.home() / "Desktop") \
        if shutil.which("xdg-user-dir") else Path.home() / "Desktop"
    paths = [desktop_dir / "sage-study.desktop", Path.home() / ".local" / "share" / "applications" / "sage-study.desktop"]
    entry = f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Comment=Quiz yourself and build study guides with Claude
Exec="{venv_python(False)}" "{LAUNCHER}"
Path={ROOT}
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
    parser.add_argument("--remove", action="store_true", help="remove the shortcut instead of creating it")
    args = parser.parse_args()
    if not args.remove:
        missing = [p for p in (venv_python(sys.platform == "win32"), LAUNCHER, ICON_DIR / "icon.png") if not p.exists()]
        if missing:
            print("Missing:", ", ".join(map(str, missing)), "\nRun the setup script first.")
            return 1
    if sys.platform == "win32":
        paths = windows(args.remove)
    elif sys.platform == "darwin":
        paths = macos(args.remove)
    else:
        paths = linux(args.remove)
    for p in paths:
        print(("Removed " if args.remove else "Created ") + str(p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
