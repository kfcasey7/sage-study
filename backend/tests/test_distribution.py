"""What sharing the app depends on: the demo, first-run state, diagnostics privacy, updates, the browser fallback,
finding the CLI, and link fetching staying off this computer and the local network."""
from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
from pathlib import Path

import httpcore
import httpx
import pytest

from sage import cli, config, db, install_info, llm_client, main as app_main, runtime
from sage.errors import AppError
from sage.services import linkfetch, updates

from .test_api import correct_answer, next_q


# --- Demo ---------------------------------------------------------------------------------------

def _no_cli(*_args, **_kwargs):
    raise AssertionError("the demo must never call Claude Code")


def test_demo_works_without_claude_code(client, monkeypatch):
    monkeypatch.setattr(llm_client, "run_cli", _no_cli)
    first = client.post("/api/demo").json()
    assert client.post("/api/demo").json() == first  # loading twice doesn't duplicate it
    view = client.get(f"/api/sets/{first['id']}").json()
    assert view["breakdown"]["status"] == "ready" and view["breakdown"]["map_mermaid"]
    assert view["subtopics"] and view["sources"][0]["status"] == "ready"
    assert view["title"].startswith("Sample:")

    guides = [g for g in view["guides"] if g["status"] == "ready"]
    assert guides and client.get(f"/api/guides/{guides[0]['id']}").json()["content"]["sections"]
    playlist = client.get(f"/api/playlists/{view['playlists'][0]['id']}").json()
    assert playlist["status"] == "ready" and all(g["videos"] for g in playlist["groups"])

    finished = [q for q in view["quizzes"] if q["status"] == "completed"]
    assert len(finished) == 1
    results = client.get(f"/api/sessions/{finished[0]['id']}/results").json()
    assert results["mastery"]["overall"]["score"] is not None

    # The other quiz can be taken from the start, graded locally, with no AI calls at all.
    ready = next(q for q in view["quizzes"] if q["status"] != "completed")
    while True:
        n = next_q(client, ready["id"])
        if n["state"] == "done":
            break
        qid = n["question"]["id"]
        r = client.post(f"/api/questions/{qid}/answer", json={"response": correct_answer(qid), "confidence": "high", "skipped": False})
        assert r.status_code == 200 and r.json()["grade_status"] == "done", r.text
    done = client.post(f"/api/sessions/{ready['id']}/finish").json()
    assert done["mastery"]["overall"]["score"] > 0


def test_demo_can_be_deleted_and_loaded_again(client, tmp_path):
    set_id = client.post("/api/demo").json()["id"]
    upload_path = config.data_path(db.query_one("SELECT path FROM uploads")["path"])
    assert upload_path.exists()
    assert client.delete(f"/api/sets/{set_id}").json() == {"ok": True}
    assert db.query_one("SELECT 1 FROM questions") is None and not upload_path.exists()
    assert client.post("/api/demo").json()["id"] == set_id
    assert upload_path.exists()


def test_demo_data_has_nothing_personal():
    text = (config.DEMO_DIR / "demo_set.json").read_text(encoding="utf-8")
    data = json.loads(text)
    for marker in ("C:\\\\", "/Users/", "/home/", "AppData", "@gmail"):
        assert marker not in text
    for upload in data["tables"]["uploads"]:
        assert upload["path"].startswith("uploads/")
    assert all(q["grade_status"] == "done" for q in data["tables"]["answers"])
    objective = {t["id"] for t in config.QUESTION_TYPES if t["grading"] == "local"}
    assert {q["type"] for q in data["tables"]["questions"]} <= objective


# --- First run --------------------------------------------------------------------------------------

def test_first_run_shows_once(client):
    assert client.get("/api/settings").json()["app"]["first_run"] is True
    assert client.put("/api/settings", json={"setup_complete": True}).json()["app"]["first_run"] is False


def test_people_who_already_use_the_app_skip_the_wizard(client):
    client.post("/api/demo")
    assert client.get("/api/settings").json()["app"]["first_run"] is False


def test_quiz_preferences_are_saved_with_the_settings(client):
    prefs = {"types": ["true_false"], "difficulty": 2, "adaptive": True, "count": 15, "languages": ["C++"]}
    assert client.put("/api/settings", json={"quiz_prefs": prefs}).json()["settings"]["quiz_prefs"] == prefs
    assert client.get("/api/settings").json()["settings"]["quiz_prefs"] == prefs


def test_page_carries_the_saved_theme_so_it_needs_no_browser_storage(client, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from sage.app import create_app

    dist = tmp_path / "web"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<html><script>t="__SAGE_THEME__"</script><div id="root"></div></html>')
    monkeypatch.setattr(config, "FRONTEND_DIST", dist)
    client.put("/api/settings", json={"theme": "dark"})
    with TestClient(create_app(), base_url="http://127.0.0.1:8765", headers={"x-sage-token": runtime.token}) as c:
        assert 't="dark"' in c.get("/").text


# --- Diagnostics ----------------------------------------------------------------------------------

def test_diagnostic_report_has_no_secrets_or_content(client, monkeypatch):
    """Canary values everywhere a leak could come from: the CLI's status output, the key store, study material."""
    from sage import secrets

    canaries = {"person@example.com": "email", "Secret Org Inc": "org", "org-abc-123": "org id", "AIzaCANARYKEY000": "api key",
                "my private lecture notes": "material", "SECRET-SET-TITLE": "set title"}
    home = str(Path.home())

    async def fake_invoke(args, stdin_text, cwd, timeout):
        if "--version" in args:
            return 0, "9.9.9 (Claude Code)\n", ""
        return 0, json.dumps({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "pro", "email": "person@example.com",
                              "orgId": "org-abc-123", "orgName": "Secret Org Inc", "configDirectory": home + "/.claude"}), ""

    monkeypatch.setattr(llm_client, "_invoke", fake_invoke)
    monkeypatch.setattr(llm_client, "find_cli", lambda: home + "/.local/bin/claude")
    monkeypatch.setattr(llm_client, "_status_cache", None)
    secrets.set_youtube_key("AIzaCANARYKEY000")
    client.post("/api/uploads", files={"file": ("notes.txt", b"my private lecture notes " * 30, "text/plain")})
    client.post("/api/sets", json={"title": "SECRET-SET-TITLE", "subject": "", "prompt": "my private lecture notes", "source_ids": []})

    body = client.get("/api/diagnostics").json()
    assert "9.9.9" in body["report"] and "Python version" in body["report"] and "Logged in to Claude Code: yes" in body["report"]
    for canary in canaries:
        assert canary not in body["report"] and canary not in json.dumps(body["items"])
    assert home not in body["report"]
    assert "~" in body["report"]


def test_cli_status_keeps_only_three_fields_from_auth_status(monkeypatch):
    async def fake_invoke(args, stdin_text, cwd, timeout):
        if "--version" in args:
            return 0, "1 (Claude Code)", ""
        return 0, json.dumps({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "max", "email": "a@b.c", "orgName": "O"}), ""

    monkeypatch.setattr(llm_client, "_invoke", fake_invoke)
    monkeypatch.setattr(llm_client, "find_cli", lambda: "claude")
    monkeypatch.setattr(llm_client, "_status_cache", None)
    status = asyncio.run(llm_client.cli_status(refresh=True))
    assert "a@b.c" not in json.dumps(status) and '"O"' not in json.dumps(status)


# --- Updates --------------------------------------------------------------------------------------

@pytest.fixture
def github(monkeypatch):
    state = {"status": 200, "tag": "v99.0.0"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.github.com"
        if state["status"] != 200:
            return httpx.Response(state["status"])
        return httpx.Response(200, json={"tag_name": state["tag"], "body": "New things", "html_url": "https://github.com/kfcasey7/sage-study/releases/tag/x"})

    monkeypatch.setattr(updates, "http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(updates, "_cache", None)
    return state


def test_update_available(client, github):
    u = client.get("/api/updates?force=true").json()
    assert u["status"] == "available" and u["latest"] == "v99.0.0" and u["notes"] == "New things"


@pytest.mark.parametrize("tag", [f"v{config.VERSION}", "v0.0.1", "not-a-version", "v1.0.0; rm -rf /", "v1.0"])
def test_update_not_offered(client, github, tag):
    github["tag"] = tag
    assert client.get("/api/updates?force=true").json()["status"] != "available"


def test_no_releases_yet_and_offline_are_quiet(client, github, monkeypatch):
    github["status"] = 404
    assert client.get("/api/updates?force=true").json()["status"] == "current"

    def boom(_):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(updates, "http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    assert client.get("/api/updates?force=true").json()["status"] == "unknown"


def test_nothing_applies_without_a_newer_release(client, github, monkeypatch):
    github["tag"] = "v0.0.1"
    monkeypatch.setattr(updates, "_spawn_updater", _no_cli)
    assert client.post("/api/updates/apply").status_code == 409


def test_installer_copy_hands_over_to_its_updater_with_githubs_tag(client, github, monkeypatch):
    spawned = []
    monkeypatch.setattr(install_info, "load", lambda: {"kind": "installer", "root": "/x"})
    monkeypatch.setattr(updates, "_spawn_updater", lambda info, tag: spawned.append(tag))
    monkeypatch.setattr(updates.desktop, "request_quit", lambda: spawned.append("quit"))
    assert client.post("/api/updates/apply").json()["action"] == "updating"
    assert spawned == ["v99.0.0", "quit"]


def test_packaged_copy_opens_the_download_page(client, github, monkeypatch):
    opened = []
    monkeypatch.setattr(install_info, "load", lambda: {"kind": "packaged"})
    monkeypatch.setattr(updates.webbrowser, "open", opened.append)
    assert client.post("/api/updates/apply").json()["action"] == "opened_download_page"
    assert opened == ["https://github.com/kfcasey7/sage-study/releases/tag/x"]


# --- Window, ports, data folder ------------------------------------------------------------------------

def test_port_is_free_and_loopback_only():
    sock = app_main.bind_free_port()
    try:
        host, port = sock.getsockname()
        assert host == "127.0.0.1" and port != config.DEV_PORT and port > 0
    finally:
        sock.close()


def test_token_differs_each_launch():
    out = [subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'backend'); from sage import runtime; print(runtime.token)"],
                          capture_output=True, text=True, check=True).stdout for _ in range(2)]
    assert out[0] != out[1] and len(out[0].strip()) >= 32


def test_data_dir_option_applies_before_config_loads(tmp_path):
    code = ("import sys; sys.path.insert(0, 'backend'); from sage import cli; "
            f"sys.exit(cli.main(['--data-dir', {str(tmp_path)!r}, '--print-data-dir']))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert Path(out.strip()) == tmp_path.resolve()


def test_nothing_is_stored_under_the_package(client):
    client.post("/api/demo")
    assert config.PACKAGE_DIR not in config.DB_PATH.parents and config.PACKAGE_DIR not in config.UPLOAD_DIR.parents


def test_window_failure_falls_back_to_the_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "INSTANCE_FILE", tmp_path / "instance.json")
    monkeypatch.setattr(config, "LOCK_FILE", tmp_path / "instance.lock")
    monkeypatch.setattr(app_main, "setup_logging", lambda: None)
    monkeypatch.setattr(app_main, "start_server", lambda sock: (type("S", (), {"should_exit": False})(), None))
    monkeypatch.setattr(runtime, "stop_requested", False)
    monkeypatch.setattr(runtime, "fallback_reason", None)

    def no_window():
        raise RuntimeError("You must have either QT or GTK")

    opened = []

    def fake_open(url):
        opened.append(url)
        runtime.stop_requested = True
        return True

    monkeypatch.setattr(app_main, "run_window", no_window)
    monkeypatch.setattr(app_main.webbrowser, "open", fake_open)
    monkeypatch.setattr(runtime, "port", 8765)
    assert app_main.main() == 0
    assert opened == [runtime.launch_url()]
    assert runtime.window_mode == "browser" and "GTK" in runtime.fallback_reason


def test_browser_mode_quits_when_the_tab_stays_gone(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(app_main.time, "monotonic", lambda: clock[0])

    def fake_sleep(_):
        clock[0] += config.BROWSER_IDLE_EXIT_SECONDS + 1

    monkeypatch.setattr(app_main.time, "sleep", fake_sleep)
    monkeypatch.setattr(app_main.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(runtime, "stop_requested", False)
    app_main.run_browser("test")  # returns instead of waiting forever


def test_heartbeat_and_quit(client, monkeypatch):
    monkeypatch.setattr(runtime, "last_heartbeat", 0.0)
    monkeypatch.setattr(runtime, "stop_requested", False)
    assert client.post("/api/_heartbeat").json() == {"ok": True}
    assert runtime.last_heartbeat > 0
    assert client.post("/api/_quit").json() == {"ok": True}
    assert runtime.stop_requested is True


def test_cli_version_flag(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert config.VERSION in capsys.readouterr().out


# --- Finding the CLI --------------------------------------------------------------------------------

def test_npm_shim_prefers_the_real_binary(tmp_path):
    shim = tmp_path / "claude.cmd"
    shim.write_text("@echo off")
    assert llm_client._prefer_native(str(shim)) == str(shim)
    native = tmp_path / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"")
    assert llm_client._prefer_native(str(shim)) == str(native)


def test_finds_the_cli_off_path(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_client.shutil, "which", lambda name: None)
    monkeypatch.setattr(llm_client.Path, "home", lambda: tmp_path)
    exe = tmp_path / ".local" / "bin" / ("claude.exe" if llm_client.sys.platform == "win32" else "claude")
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert llm_client.find_cli() == str(exe)


def test_network_failures_get_their_own_error():
    err = llm_client.classify("API Error: Connection error. getaddrinfo ENOTFOUND api.anthropic.com")
    assert isinstance(err, AppError) and err.code == "network" and err.retryable


def test_safety_flags_are_still_on_every_call():
    args = llm_client.build_args("claude", llm_client.CliRequest(model="haiku", prompt="p", schema={}))
    for flag in ("--restricted", "--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"):
        assert flag in args
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--permission-prompts") + 1] == "none"
    assert args[args.index("--setting-sources") + 1] == ""


def test_api_key_variables_are_still_stripped(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK"):
        monkeypatch.setenv(name, "x")
    env = llm_client.child_env()
    assert not {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK"} & set(env)


# --- Link fetching -------------------------------------------------------------------------------------

@pytest.mark.parametrize("host", [
    "127.0.0.1", "127.8.8.8", "localhost", "foo.localhost", "printer.local", "10.1.2.3", "172.16.0.1", "192.168.1.1",
    "169.254.169.254", "100.64.0.1", "0.0.0.0", "[::1]", "[::ffff:127.0.0.1]", "[fe80::1]", "[fc00::1]", "224.0.0.1",
])
def test_non_public_addresses_are_refused(host):
    assert linkfetch._is_private_host(host) is True


@pytest.mark.parametrize("host", ["8.8.8.8", "1.1.1.1", "[2606:4700:4700::1111]"])
def test_public_addresses_are_allowed(host):
    assert linkfetch._is_private_host(host) is False


class _Inner:
    def __init__(self):
        self.connected: list[str] = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.connected.append(host)
        return "stream"


async def test_connection_goes_to_the_address_that_was_checked(monkeypatch):
    inner = _Inner()
    backend = linkfetch.PublicOnlyBackend(inner)
    monkeypatch.setattr(linkfetch, "resolve", lambda host: ["93.184.216.34"])
    assert await backend.connect_tcp("example.com", 443) == "stream"
    assert inner.connected == ["93.184.216.34"]  # the IP, so no second lookup can change the answer


async def test_a_name_resolving_to_this_computer_is_refused_at_connect_time(monkeypatch):
    inner = _Inner()
    backend = linkfetch.PublicOnlyBackend(inner)
    monkeypatch.setattr(linkfetch, "resolve", lambda host: ["93.184.216.34", "127.0.0.1"])
    with pytest.raises(linkfetch.LinkError):
        await backend.connect_tcp("rebind.example", 443)
    assert inner.connected == []


async def test_unresolvable_names_fail_as_a_connection_error(monkeypatch):
    def fail(host):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(linkfetch, "resolve", fail)
    with pytest.raises(httpcore.ConnectError):
        await linkfetch.PublicOnlyBackend(_Inner()).connect_tcp("nope.example", 443)


def test_the_real_transport_uses_the_guarded_backend():
    """public_transport reaches into httpx internals, so an upgrade that moves them must fail here, loudly."""
    transport = linkfetch.public_transport()
    assert isinstance(transport._pool._network_backend, linkfetch.PublicOnlyBackend)


async def test_guarded_client_really_cannot_reach_a_local_server(monkeypatch):
    """A name that passes the first check and only then resolves to loopback still can't connect."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    monkeypatch.setattr(linkfetch, "is_private_host", lambda host: False)
    monkeypatch.setattr(linkfetch, "resolve", lambda host: ["127.0.0.1"])
    try:
        async with linkfetch.make_client() as client:
            with pytest.raises(linkfetch.LinkError):
                await client.get(f"http://rebind.example:{port}/")
    finally:
        server.close()
