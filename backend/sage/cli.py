"""Command-line entry point (`sage-study`, and `sage-study-gui` for shortcuts, which opens no console).

--data-dir has to take effect before anything imports `config`, so every other import here is deferred."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from . import __version__


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="sage-study", description="Sage Study: a personal study assistant that works with Claude Code.")
    parser.add_argument("--version", action="version", version=f"Sage Study {__version__}")
    parser.add_argument("--data-dir", metavar="FOLDER", help="keep the database, uploads, and logs in this folder")
    parser.add_argument("--browser", action="store_true", help="open in the default browser instead of a native window")
    parser.add_argument("--check", action="store_true", help="check that Claude Code is ready, then exit")
    parser.add_argument("--smoke-test", action="store_true", help="start the app without a window, exercise it, and exit")
    parser.add_argument("--print-data-dir", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--forget-youtube-key", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def check() -> int:
    """Plain-English first-run checks, for the installers. Never a failure: the app's wizard can fix these too."""
    from . import config, llm_client

    status = asyncio.run(llm_client.cli_status(refresh=True))
    print(f"[{'ok' if status['installed'] else '!!'}] Claude Code {'found: ' + (status['version'] or '') if status['installed'] else 'is not installed yet'}")
    print(f"[{'ok' if status['logged_in'] else '!!'}] {'Signed in to Claude Code' if status['logged_in'] else 'Not signed in to Claude Code yet'}")
    if not status["ready"]:
        print(f"\nNo problem: Sage Study will walk you through this when it opens.\nInstructions: {config.CLAUDE_CODE_DOCS_URL}")
    return 0


def smoke_test() -> int:
    """Start the real server on a free port and run a user's first minute against it: sign in with the launch
    token, load the page, check Claude Code, and open the demo set. Used by CI and the installers' tests."""
    import http.cookiejar
    import urllib.error
    import urllib.request

    from . import main as app_main
    from . import runtime

    server, _ = app_main.start_server(app_main.bind_free_port())
    base = runtime.server_url()
    try:
        try:
            urllib.request.urlopen(base + "/api/settings", timeout=10)
            raise AssertionError("the API answered without the launch token")
        except urllib.error.HTTPError as e:
            assert e.code == 401, e.code

        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        with opener.open(runtime.launch_url(), timeout=10) as r:
            page = r.read().decode()
            assert 'id="root"' in page, "the UI page didn't load"

        def call(method: str, path: str) -> dict:
            req = urllib.request.Request(base + path, method=method, data=b"" if method != "GET" else None, headers={"x-sage-client": "1"})
            with opener.open(req, timeout=60) as r:
                return json.loads(r.read())

        print("version:", call("GET", "/api/settings")["app"]["version"])
        print("claude code:", call("GET", "/api/settings/cli-status?refresh=true")["ready"])
        print("diagnostics:", len(call("GET", "/api/diagnostics")["report"]), "chars")
        demo = call("POST", "/api/demo")
        view = call("GET", f"/api/sets/{demo['id']}")
        assert view["breakdown"]["status"] == "ready", view["breakdown"]
        print("demo set:", view["title"], "with", len(view["subtopics"]), "subtopics")
    finally:
        server.should_exit = True
    print("smoke test passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.data_dir:
        os.environ["SAGE_DATA_DIR"] = str(Path(args.data_dir).expanduser().resolve())
    if args.print_data_dir:
        from . import config

        print(config.DATA_DIR)
        return 0
    if args.forget_youtube_key:
        from . import secrets

        secrets.delete_youtube_key()
        return 0
    if args.check:
        return check()
    if args.smoke_test:
        return smoke_test()
    from . import main as app_main

    return app_main.main(force_browser=args.browser or os.environ.get("SAGE_FORCE_BROWSER") == "1")


if __name__ == "__main__":
    sys.exit(main())
