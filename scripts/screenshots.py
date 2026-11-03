"""Drive the real app (through the launch-token sign-in) on a temporary data folder, check the main screens for errors, and
save the README screenshots from the demo Study Set.

    uv run --with playwright python scripts/screenshots.py

Uses the Microsoft Edge or Chrome already on this computer. Also checks that the theme survives a restart on a new port.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"
SERVER = """
import sys, time
sys.path.insert(0, sys.argv[1])
from sage import main, runtime
main.start_server(main.bind_free_port())
print(runtime.launch_url(), flush=True)
time.sleep(600)
"""


def start_app(data: Path) -> tuple[subprocess.Popen, str]:
    env = {**os.environ, "SAGE_DATA_DIR": str(data)}
    proc = subprocess.Popen([sys.executable, "-c", SERVER, str(ROOT / "backend")], env=env, stdout=subprocess.PIPE, text=True)
    url = proc.stdout.readline().strip()
    assert url.startswith("http://127.0.0.1:"), url
    return proc, url


def run(servers: list[subprocess.Popen]) -> int:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    data = Path(tempfile.mkdtemp(prefix="sage-shots-"))
    problems: list[str] = []
    proc, url = start_app(data)
    servers.append(proc)
    with sync_playwright() as p:
        browser = None
        for channel in ("msedge", "chrome"):
            try:
                browser = p.chromium.launch(channel=channel)
                break
            except Exception:  # noqa: BLE001 - try the next browser
                continue
        assert browser, "needs Edge or Chrome"
        context = browser.new_context(viewport={"width": 1280, "height": 860}, device_scale_factor=1.5)
        context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = context.new_page()
        page.on("console", lambda m: problems.append(f"console {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: problems.append(f"pageerror {e}"))
        page.on("response", lambda r: problems.append(f"{r.status} {r.url}") if r.status >= 400 and "127.0.0.1" in r.url else None)

        def shot(name: str, wait: float = 1.2) -> None:
            time.sleep(wait)
            page.screenshot(path=OUT / f"{name}.png")
            print("saved", name, flush=True)

        def api(path: str):
            return page.request.get(url.split("/launch")[0] + path).json()

        page.goto(url)
        page.wait_for_url("**/")
        assert "token" not in page.url, "the token must leave the address bar"
        page.get_by_role("heading", name="Welcome to Sage Study").wait_for()
        page.get_by_text("You're signed in to Claude Code").or_(page.get_by_text("You're not signed in")).or_(page.get_by_text("isn't installed yet")).first.wait_for(timeout=40000)
        shot("welcome")

        page.get_by_role("button", name="Try a demo").click()
        page.get_by_text("Sample: The First Law of Thermodynamics").first.wait_for()
        page.wait_for_selector("svg[aria-roledescription]", timeout=20000)
        shot("breakdown", 2)

        set_id = page.url.rsplit("/", 1)[-1]
        view = api(f"/api/sets/{set_id}")
        finished = next(q for q in view["quizzes"] if q["status"] == "completed")["id"]
        ready = next(q for q in view["quizzes"] if q["status"] != "completed")["id"]
        base = url.split("/launch")[0]

        page.goto(f"{base}/#/results/{finished}")
        page.wait_for_selector(".score-ring", timeout=15000)
        shot("results", 2)

        page.goto(f"{base}/#/study-guides/{view['guides'][0]['id']}")
        page.wait_for_selector(".katex", timeout=20000)
        shot("guide", 2.5)

        page.goto(f"{base}/#/playlists/{view['playlists'][0]['id']}")
        page.get_by_text("Copy all links").first.wait_for(timeout=15000)
        shot("playlist", 2.5)

        page.goto(f"{base}/#/quiz/{ready}")
        page.get_by_role("button", name="Submit").first.wait_for(timeout=20000)
        shot("quiz", 1.5)

        page.goto(f"{base}/#/settings/diagnostics")
        page.get_by_role("button", name="Copy diagnostic report").click()
        time.sleep(0.5)
        report = page.evaluate("navigator.clipboard.readText()")
        assert "Sage Study diagnostic report" in report and "App version" in report, report
        assert "@" not in report and str(Path.home()) not in report, report
        shot("diagnostics")

        page.goto(f"{base}/#/settings")
        page.get_by_role("button", name="Dark", exact=True).click()
        time.sleep(0.5)
        browser.close()

    proc.terminate()
    proc.wait(timeout=20)

    # Restart: a new port and a new origin, and the theme must still be there.
    proc, url2 = start_app(data)
    servers.append(proc)
    assert url2.split("/launch")[0] != url.split("/launch")[0], "the port should change between launches"
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge") if os.name == "nt" else p.chromium.launch(channel="chrome")
        page = browser.new_page()
        page.goto(url2)
        page.wait_for_url("**/")
        theme = page.evaluate("document.documentElement.dataset.theme")
        assert theme == "dark", f"the theme was lost across a restart: {theme}"
        first_run = page.request.get(url2.split("/launch")[0] + "/api/settings").json()["app"]["first_run"]
        assert first_run is False
        browser.close()
    proc.terminate()
    proc.wait(timeout=20)

    # 403s from YouTube and similar third parties don't count; only the app's own errors do.
    print(json.dumps(problems, indent=1))
    if problems:
        print(f"{len(problems)} problem(s) above")
        return 1
    print("All screens loaded with no errors.")
    return 0


def main() -> int:
    servers: list[subprocess.Popen] = []
    try:
        return run(servers)
    finally:
        for proc in servers:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
