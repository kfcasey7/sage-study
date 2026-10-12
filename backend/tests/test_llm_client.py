"""Tests for the Claude Code CLI wrapper, with the subprocess mocked."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from sage import config, db, llm_client
from sage.errors import AppError
from sage.ingest import Material

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False}


class Answer(BaseModel):
    answer: str

    @classmethod
    def strict(cls, data):
        obj = cls.model_validate(data)
        if obj.answer == "bad":
            raise ValueError("answer must not be 'bad'")
        return obj


def ok_output(payload: dict | None = None, **extra) -> str:
    payload = payload if payload is not None else {"answer": "H2O"}
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "duration_ms": 1500,
                       "result": json.dumps(payload), "structured_output": payload, **extra})


def err_output(message: str, status=None) -> str:
    return json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": message, "api_error_status": status})


class FakeProc:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0, hang: bool = False, on_run=None):
        self.stdout, self.stderr, self.returncode, self.hang, self.on_run = stdout, stderr, returncode, hang, on_run
        self.stdin: bytes | None = None
        self.killed = False

    async def communicate(self, input=None):
        self.stdin = input
        if self.on_run:
            self.on_run()
        if self.hang:
            await asyncio.sleep(3600)
        return self.stdout.encode(), self.stderr.encode()

    def kill(self):
        self.killed = True

    async def wait(self):
        return -9


class Spawner:
    """Replaces asyncio.create_subprocess_exec; returns queued FakeProcs and records each call."""

    def __init__(self, *procs: FakeProc):
        self.procs = list(procs)
        self.calls: list[dict] = []

    async def __call__(self, *args, **kwargs):
        proc = self.procs.pop(0)
        self.calls.append({"args": list(args), "kwargs": kwargs, "proc": proc})
        if isinstance(proc, BaseException):
            raise proc
        return proc


@pytest.fixture
def spawn(monkeypatch):
    def install(*procs):
        s = Spawner(*procs)
        monkeypatch.setattr(llm_client.asyncio, "create_subprocess_exec", s)
        return s
    monkeypatch.setattr(llm_client, "find_cli", lambda: "claude")
    return install


def ctx(**kw) -> llm_client.CallContext:
    return llm_client.CallContext(session_id="s1", material=Material(texts=[("notes.txt", "Water is H2O.")]),
                                  preamble="<coverage_request>Chemistry</coverage_request>", **kw)


async def call(purpose="generate", validate=Answer.model_validate, c=None):
    return await llm_client.structured_call(c or ctx(), purpose=purpose, instruction="What is water?", schema=SCHEMA, validate=validate)


def flag_value(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


# --- Happy path & flags ---------------------------------------------------------------------

async def test_success_builds_safe_cli_invocation(spawn, monkeypatch):
    for k, v in {"ANTHROPIC_API_KEY": "sk-ant-secret", "ANTHROPIC_AUTH_TOKEN": "t", "ANTHROPIC_BASE_URL": "http://x",
                 "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDECODE": "1", "SAGE_KEEP_ME": "yes"}.items():
        monkeypatch.setenv(k, v)
    s = spawn(FakeProc(ok_output()))
    result = await call()
    assert result.answer == "H2O"

    args, kwargs = s.calls[0]["args"], s.calls[0]["kwargs"]
    assert args[:2] == ["claude", "-p"]
    assert flag_value(args, "--output-format") == "json"
    assert flag_value(args, "--model") == "haiku"                   # question writing -> fast model
    assert flag_value(args, "--tools") == ""                        # no tools at all
    assert flag_value(args, "--setting-sources") == ""              # no user hooks/permissions
    assert flag_value(args, "--permission-prompts") == "none"
    for flag in ("--restricted", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in args
    assert json.loads(flag_value(args, "--json-schema")) == SCHEMA
    assert "Sage" in flag_value(args, "--system-prompt")

    env = kwargs["env"]
    assert not any(k.startswith("ANTHROPIC_") for k in env)
    assert "CLAUDE_CODE_USE_BEDROCK" not in env and "CLAUDECODE" not in env
    assert env["SAGE_KEEP_ME"] == "yes"

    prompt = s.calls[0]["proc"].stdin.decode()
    assert '<document title="notes.txt">\nWater is H2O.\n</document>' in prompt
    assert "Chemistry" in prompt and "What is water?" in prompt
    assert prompt.rstrip().endswith("No prose before or after it.")

    work = Path(kwargs["cwd"])
    assert work.parent == config.LLM_TMP_DIR and not work.exists()  # work folder cleaned up
    row = db.query_one("SELECT * FROM ai_calls")
    assert (row["purpose"], row["model"], row["ok"], row["duration_ms"]) == ("generate", "haiku", 1, 1500)


async def test_grading_uses_smart_model(spawn):
    s = spawn(FakeProc(ok_output()))
    await call(purpose="grade", c=ctx(model_smart="opus"))
    assert flag_value(s.calls[0]["args"], "--model") == "opus"


async def test_files_are_copied_into_sandbox_with_read_tool(spawn, tmp_path):
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"jpegdata")
    seen = {}

    def inspect():
        work = Path(spawner.calls[-1]["kwargs"]["cwd"])
        seen["files"] = sorted(p.name for p in work.iterdir())

    spawner = spawn(FakeProc(ok_output(), on_run=inspect))
    c = ctx()
    c.material.files.append(("Lecture notes.JPG", photo, "image"))
    await call(c=c)
    args = spawner.calls[0]["args"]
    assert flag_value(args, "--tools") == "Read" and "--restricted" in args
    assert seen["files"] == ["01-Lecture_notes.jpg"]
    prompt = spawner.calls[0]["proc"].stdin.decode()
    assert "01-Lecture_notes.jpg" in prompt and "Read tool" in prompt
    assert not Path(spawner.calls[0]["kwargs"]["cwd"]).exists()


async def test_json_in_result_text_is_accepted_without_structured_output(spawn):
    out = json.dumps({"type": "result", "subtype": "success", "is_error": False,
                      "result": 'Here you go:\n```json\n{"answer": "NaCl"}\n```'})
    spawn(FakeProc(out))
    assert (await call()).answer == "NaCl"


async def test_stray_log_lines_before_json_are_ignored(spawn):
    spawn(FakeProc("warning: something\n" + ok_output()))
    assert (await call()).answer == "H2O"


# --- Validation retries ------------------------------------------------------------------

async def test_retry_includes_validation_error_then_succeeds(spawn):
    s = spawn(FakeProc(ok_output({"answer": "bad"})), FakeProc(ok_output({"wrong": 1})), FakeProc(ok_output({"answer": "good"})))
    assert (await call(validate=Answer.strict)).answer == "good"
    prompts = [c["proc"].stdin.decode() for c in s.calls]
    assert "previous_attempt_error" not in prompts[0]
    assert "answer must not be 'bad'" in prompts[1]
    assert "answer" in prompts[2] and "Field required" in prompts[2]
    rows = db.query("SELECT ok, error_code FROM ai_calls ORDER BY id")
    assert [(r["ok"], r["error_code"]) for r in rows] == [(0, "invalid_output"), (0, "invalid_output"), (1, None)]


async def test_gives_up_after_two_retries(spawn):
    s = spawn(*[FakeProc(ok_output({"answer": "bad"})) for _ in range(3)])
    with pytest.raises(AppError) as e:
        await call(validate=Answer.strict)
    assert e.value.code == "invalid_output" and len(s.calls) == 3


# --- Error detection ---------------------------------------------------------------------

@pytest.mark.parametrize("stdout,stderr,code,needle", [
    (err_output("Invalid API key · Please run /login"), "", "not_logged_in", "log in"),
    (err_output("Not logged in · Please run /login"), "", "not_logged_in", "claude"),
    (err_output("Claude AI usage limit reached|1760000000"), "", "usage_limit", "around"),
    (err_output("You've hit your limit · resets 3pm (America/New_York)"), "", "usage_limit", "3pm"),
    (err_output("API Error: Rate limited", 429), "", "usage_limit", "usage limit reached"),
    (err_output("API Error: Overloaded", 529), "", "overloaded", "overloaded"),
    ("", "Error: Invalid API key. Please run /login", "not_logged_in", "log in"),
    ("not json at all", "boom", "cli_error", "usable response"),
    (err_output("Something unexpected"), "", "cli_error", "reported an error"),
])
async def test_error_detection(spawn, stdout, stderr, code, needle):
    spawn(FakeProc(stdout, stderr, returncode=1))
    with pytest.raises(AppError) as e:
        await call()
    assert e.value.code == code and needle in e.value.message
    assert db.query_one("SELECT ok, error_code FROM ai_calls")["error_code"] == code


async def test_usage_limit_message_is_friendly(spawn):
    spawn(FakeProc(err_output("Claude AI usage limit reached|1760000000")))
    with pytest.raises(AppError) as e:
        await call()
    assert e.value.message.startswith("Claude usage limit reached — try again after it resets")
    assert e.value.retryable


async def test_refusal(spawn):
    spawn(FakeProc(ok_output(stop_reason="refusal")))
    with pytest.raises(AppError) as e:
        await call()
    assert e.value.code == "refusal"


async def test_timeout_kills_process(spawn, monkeypatch):
    monkeypatch.setitem(config.TASK_TIMEOUT, "generate", 0.05)
    s = spawn(FakeProc(hang=True))
    with pytest.raises(AppError) as e:
        await call()
    assert e.value.code == "timeout" and s.calls[0]["proc"].killed
    assert not any(config.LLM_TMP_DIR.iterdir()) if config.LLM_TMP_DIR.exists() else True


async def test_cli_not_installed(monkeypatch):
    monkeypatch.setattr(llm_client, "find_cli", lambda: None)
    with pytest.raises(AppError) as e:
        await call()
    assert e.value.code == "cli_missing" and "Claude Code isn't installed" in e.value.message


async def test_cli_binary_vanished(spawn):
    spawn(FileNotFoundError("claude"))
    with pytest.raises(AppError) as e:
        await call()
    assert e.value.code == "cli_missing"


# --- Status ------------------------------------------------------------------------------

async def test_cli_status_ready(spawn):
    spawn(FakeProc("2.1.296 (Claude Code)\n"),
          FakeProc(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "pro"})))
    st = await llm_client.cli_status(refresh=True)
    assert st["ready"] and st["version"] == "2.1.296 (Claude Code)" and st["subscription"] == "pro" and st["message"] is None


async def test_cli_status_not_logged_in(spawn):
    spawn(FakeProc("2.1.296 (Claude Code)\n"), FakeProc(json.dumps({"loggedIn": False})))
    st = await llm_client.cli_status(refresh=True)
    assert st["installed"] and not st["ready"] and "not logged in" in st["message"]


async def test_cli_status_missing(monkeypatch):
    monkeypatch.setattr(llm_client, "find_cli", lambda: None)
    st = await llm_client.cli_status(refresh=True)
    assert not st["installed"] and not st["ready"] and "isn't installed" in st["message"]


def test_classify_ignores_ordinary_text():
    assert llm_client.classify("The gas expands isothermally.") is None
