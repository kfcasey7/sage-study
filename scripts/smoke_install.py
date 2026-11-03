"""End-to-end test of the one-step installer: install from this folder into a throwaway location with a fake home, a fake
data folder, and a mocked Claude Code CLI; run the app's smoke test; check the shortcuts; uninstall; and confirm nothing
is left behind except the data you chose to keep. CI runs this on Windows, macOS, and Ubuntu.

    python scripts/smoke_install.py
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = sys.platform == "win32"

FAKE_CLI = """#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if "--version" in args:
    print("0.0.0 (Claude Code, mocked)")
elif args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "pro", "email": "should-not-appear@example.com"}))
else:
    sys.exit("the mock only answers --version and auth status")
"""


def run(cmd: list[str], env: dict[str, str], **kw) -> subprocess.CompletedProcess:
    print("$", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, env=env, text=True, capture_output=True, encoding="utf-8", errors="replace", **kw)
    print(result.stdout, result.stderr, flush=True)
    if result.returncode != 0:
        raise SystemExit(f"failed with exit code {result.returncode}: {' '.join(cmd)}")
    return result


def fake_claude(folder: Path) -> None:
    folder.mkdir(parents=True)
    script = folder / "claude_mock.py"
    script.write_text(FAKE_CLI, encoding="utf-8")
    if WINDOWS:
        (folder / "claude.cmd").write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        launcher = folder / "claude"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def files_under(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="sage install test "))  # a space on purpose: paths with spaces must work
    home, data, install_root, shortcuts, mock = work / "home", work / "my data", work / "app root", work / "shortcuts", work / "mock"
    home.mkdir()
    fake_claude(mock)
    env = {**os.environ, "SAGE_INSTALL_ROOT": str(install_root), "SAGE_SHORTCUT_ROOT": str(shortcuts), "SAGE_INSTALL_NONINTERACTIVE": "1",
           "HOME": str(home), "XDG_DATA_HOME": str(home / ".local" / "share"), "PATH": str(mock) + os.pathsep + os.environ["PATH"]}
    if WINDOWS:
        env.update(USERPROFILE=str(home), LOCALAPPDATA=str(home / "AppData" / "Local"), APPDATA=str(home / "AppData" / "Roaming"))
        (home / "AppData" / "Local").mkdir(parents=True)
        (home / "AppData" / "Roaming").mkdir(parents=True)

    def install() -> None:
        if WINDOWS:
            run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "installer" / "install.ps1"),
                 "-DataDir", str(data), "-NoLaunch"], env)
        else:
            run(["sh", str(ROOT / "install.sh"), "--data-dir", str(data), "--no-launch"], env)

    try:
        install()
        env_bin = install_root / "tools" / "sage-study" / ("Scripts" if WINDOWS else "bin")
        app = env_bin / ("sage-study.exe" if WINDOWS else "sage-study")

        print("--- the app runs from the installed environment, away from the source folder")
        where = run([str(env_bin / ("python.exe" if WINDOWS else "python")), "-c",
                     "import sage, sage.config as c; print(sage.__file__); print(c.FRONTEND_DIST); print((c.FRONTEND_DIST / 'index.html').exists())"], env, cwd=str(home)).stdout
        assert str(ROOT) not in where, where
        assert where.strip().endswith("True"), "the built UI didn't ship with the package"
        out = run([str(app), "--data-dir", str(data), "--smoke-test"], env, cwd=str(home)).stdout
        assert "smoke test passed" in out and "should-not-appear" not in out
        check = run([str(app), "--data-dir", str(data), "--check"], env, cwd=str(home)).stdout
        assert "Signed in to Claude Code" in check, check
        assert (data / "sage.db").exists()
        assert not any(p.suffix == ".db" for p in install_root.rglob("*.db")), "data must not live in the install folder"

        print("--- shortcuts")
        made = files_under(shortcuts)
        print(made)
        assert made, "no shortcuts were created"
        if WINDOWS:
            assert {"Desktop\\Sage Study.lnk", "StartMenu\\Sage Study.lnk", "StartMenu\\Uninstall Sage Study.lnk"} <= set(made), made
        elif sys.platform == "darwin":
            assert any("Sage Study.app" in m for m in made), made
        else:
            assert "Desktop/sage-study.desktop" in made and "applications/sage-study.desktop" in made, made

        print("--- running the installer again repairs a broken install")
        (env_bin / ("python.exe" if WINDOWS else "python")).unlink()
        install()
        out = run([str(app), "--data-dir", str(data), "--smoke-test"], env, cwd=str(home)).stdout
        assert "smoke test passed" in out
        assert (data / "sage.db").exists(), "repairing must keep the data"

        print("--- the marker tells the app how it was installed")
        kind = run([str(env_bin / ("python.exe" if WINDOWS else "python")), "-c", "from sage import install_info; print(install_info.load()['kind'])"], env).stdout
        assert kind.strip() == "installer", kind
        marker = json.loads((install_root / "sage-install.json").read_text(encoding="utf-8"))
        assert marker["data_dir"] == str(data)

        print("--- uninstall, keeping the data")
        if WINDOWS:
            run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(install_root / "uninstall.ps1"), "-KeepData"], env)
        else:
            run(["sh", str(install_root / "uninstall.sh"), "--keep-data"], env)
        assert not install_root.exists(), "the install folder is still there"
        left = files_under(shortcuts) if shortcuts.exists() else []
        assert not left, f"shortcuts left behind: {left}"
        assert (data / "sage.db").exists(), "kept data is gone"
        strays = [f for f in files_under(home) if "PowerShell" not in f]  # PowerShell's own caches, from running the scripts
        assert not strays, f"left behind in the home folder: {strays}"

        print("--- uninstall when asked to delete the data")
        install()
        if WINDOWS:
            run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(install_root / "uninstall.ps1"), "-DeleteData"], env)
        else:
            run(["sh", str(install_root / "uninstall.sh"), "--delete-data"], env)
        assert not install_root.exists() and not data.exists()
        print("\nInstall smoke test passed.")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
