"""The only module that talks to the AI: it runs the locally installed Claude Code CLI (`claude -p`)
as an async subprocess, using the user's Claude subscription login.

Every call:
  * strips ANTHROPIC_* and third-party-provider variables from the child environment, so the CLI can
    never fall back to API-key billing;
  * disables MCP servers, user/project settings (hooks, permissions), slash commands, and every built-in
    tool. Calls that include images or scanned PDFs get only the Read tool, confined (--restricted) to a
    temp folder holding copies of those files;
  * asks for JSON matching a schema (--json-schema), validates it with Pydantic, and retries with the
    validation error up to VALIDATION_RETRIES times;
  * has a timeout and maps failures to clear error codes (cli_missing, not_logged_in, usage_limit,
    timeout, refusal, invalid_output, cli_error).

The CLI has no max-turns flag; with no tools (or only Read on a few files) there is nothing to loop on,
and the timeout bounds every call."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TypeVar

from pydantic import ValidationError

from . import config, db
from .errors import AppError
from .ingest import Material, select_text
from .prompts.system import SYSTEM_PROMPT

log = logging.getLogger(__name__)
T = TypeVar("T")

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
STRIP_ENV_PREFIXES = ("ANTHROPIC_",)
STRIP_ENV_NAMES = {
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "AWS_BEARER_TOKEN_BEDROCK", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT",
}


@dataclass
class CallContext:
    session_id: str | None
    model_fast: str = config.DEFAULT_MODEL_FAST
    model_smart: str = config.DEFAULT_MODEL_SMART
    material: Material = field(default_factory=Material)
    preamble: str = ""


@dataclass
class CliRequest:
    model: str
    prompt: str
    schema: dict[str, Any]
    files: list[tuple[str, Path]] = field(default_factory=list)  # (name in work folder, source path)
    timeout: float = 300
    system: str = SYSTEM_PROMPT


# --- Environment & discovery --------------------------------------------------------------

def child_env() -> dict[str, str]:
    return {
        k: v for k, v in os.environ.items()
        if not k.upper().startswith(STRIP_ENV_PREFIXES) and k.upper() not in STRIP_ENV_NAMES
    }


def find_cli() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    candidates = [
        home / ".local" / "bin" / ("claude.exe" if sys.platform == "win32" else "claude"),
        home / ".claude" / "local" / ("claude.exe" if sys.platform == "win32" else "claude"),
        Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd",
        Path("/usr/local/bin/claude"),
        Path("/opt/homebrew/bin/claude"),
    ]
    return next((str(c) for c in candidates if c.is_file()), None)


# --- Subprocess -------------------------------------------------------------------------------

async def _invoke(args: list[str], stdin_text: str, cwd: Path, timeout: float) -> tuple[int, str, str]:
    """Run the CLI; returns (returncode, stdout, stderr). Raises AppError on timeout / missing binary."""
    kwargs: dict[str, Any] = {"creationflags": NO_WINDOW} if sys.platform == "win32" else {}
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd), env=child_env(), **kwargs,
        )
    except FileNotFoundError as e:
        raise cli_missing_error() from e
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin_text.encode("utf-8")), timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise AppError("timeout", f"Claude took longer than {int(timeout)} seconds to respond, so the request was stopped. Try again.") from None
    return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def cli_missing_error() -> AppError:
    return AppError(
        "cli_missing",
        "Claude Code isn't installed or isn't on your PATH. Install it from https://claude.com/claude-code, then run "
        "`claude` once in a terminal and log in with your Claude account.",
    )


def build_args(cli: str, req: CliRequest) -> list[str]:
    return [
        cli, "-p",
        "--output-format", "json",
        "--model", req.model,
        "--system-prompt", req.system,
        "--json-schema", json.dumps(req.schema, separators=(",", ":")),
        "--tools", "Read" if req.files else "",
        "--restricted",                    # no shell/code tools; file tools confined to the work folder
        "--permission-prompts", "none",    # anything that would need approval is denied
        "--strict-mcp-config",             # ignore the user's MCP servers
        "--setting-sources", "",           # ignore user/project settings (hooks, permissions)
        "--disable-slash-commands",
        "--no-session-persistence",
    ]


# --- Error classification ---------------------------------------------------------------------

_USAGE = re.compile(r"usage limit|limit reached|hit your (?:usage |session |weekly )?limit|limit (?:will )?reset|"
                    r"out of (?:extra )?usage|rate[ _-]?limit|too many requests|\b429\b", re.I)
_LOGIN = re.compile(r"not logged in|please (?:run )?/login|run `?claude`? (?:to|and) log ?in|log ?in (?:again|required)|"
                    r"invalid api key|authentication|unauthori[sz]ed|oauth token|credentials|\b401\b", re.I)
_OVERLOADED = re.compile(r"overloaded|\b529\b", re.I)
_RESET_EPOCH = re.compile(r"\|(\d{10})\b")
_RESET_TEXT = re.compile(r"resets? (?:at |on )?([0-9]{1,2}(?::[0-9]{2})?\s*(?:[ap]\.?m\.?)?(?:\s*\([^)]*\))?)", re.I)


def classify(text: str, status: Any = None) -> AppError | None:
    blob = f"{text} {status or ''}"
    if _USAGE.search(blob):
        reset = None
        if (m := _RESET_EPOCH.search(blob)):
            reset = datetime.fromtimestamp(int(m.group(1))).strftime("%I:%M %p").lstrip("0")
        elif (m := _RESET_TEXT.search(blob)):
            reset = m.group(1).strip()
        when = f" (around {reset})" if reset else ""
        return AppError("usage_limit", f"Claude usage limit reached — try again after it resets{when}. Your progress is saved.",
                        detail=text[:300])
    if _LOGIN.search(blob):
        return AppError("not_logged_in", "Claude Code isn't logged in. Open a terminal, run `claude`, and log in with your "
                        "Claude account (type /login if it doesn't prompt you).", detail=text[:300])
    if _OVERLOADED.search(blob):
        return AppError("overloaded", "Claude is temporarily overloaded. Try again in a moment.", detail=text[:300])
    return None


def parse_result(returncode: int, stdout: str, stderr: str) -> dict[str, Any]:
    """Parse `--output-format json` output, turning CLI-level failures into AppErrors."""
    data: Any = None
    text = stdout.strip()
    if text:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Tolerate stray log lines: use the last line that parses as a JSON object.
            for line in reversed(text.splitlines()):
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
    if isinstance(data, list):  # some versions emit a list of events; the result is the last
        data = next((d for d in reversed(data) if isinstance(d, dict) and d.get("type") == "result"), None)
    if not isinstance(data, dict):
        raise classify(f"{stdout}\n{stderr}") or AppError(
            "cli_error", "Claude Code exited without a usable response.", detail=(stderr or stdout).strip()[-500:] or f"exit code {returncode}")
    if data.get("is_error") or data.get("subtype") not in (None, "success"):
        msg = str(data.get("result") or data.get("error") or data.get("subtype") or "")
        raise classify(f"{msg}\n{stderr}", data.get("api_error_status")) or AppError(
            "cli_error", "Claude Code reported an error.", detail=msg[-500:] or str(data.get("subtype")))
    if data.get("stop_reason") == "refusal":
        raise AppError("refusal", "Claude declined this request. If your material is ordinary course content, try rephrasing "
                       "what to cover or removing unrelated files.")
    return data


def extract_json(data: dict[str, Any]) -> dict[str, Any]:
    """The structured result: `structured_output` when --json-schema was honoured, else JSON in the text."""
    so = data.get("structured_output")
    if isinstance(so, dict):
        return so
    text = str(data.get("result") or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("the response contained no JSON object")
    obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("the response JSON is not an object")
    return obj


# --- Running a request ------------------------------------------------------------------------

_semaphore: asyncio.Semaphore | None = None
_semaphore_loop: asyncio.AbstractEventLoop | None = None


def _sem() -> asyncio.Semaphore:
    global _semaphore, _semaphore_loop
    loop = asyncio.get_running_loop()
    if _semaphore is None or _semaphore_loop is not loop:
        _semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_CALLS)
        _semaphore_loop = loop
    return _semaphore


async def run_cli(req: CliRequest) -> dict[str, Any]:
    """One CLI invocation; returns the parsed result object. Files are copied into a fresh work
    folder (the only place the Read tool can see) and removed afterwards."""
    cli = find_cli()
    if not cli:
        raise cli_missing_error()
    work = config.LLM_TMP_DIR / uuid.uuid4().hex[:12]
    work.mkdir(parents=True, exist_ok=True)
    try:
        for name, src in req.files:
            shutil.copyfile(src, work / name)
        async with _sem():
            code, out, err = await _invoke(build_args(cli, req), req.prompt, work, req.timeout)
        return parse_result(code, out, err)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def cleanup_tmp() -> None:
    """Remove work folders left behind by a crash."""
    shutil.rmtree(config.LLM_TMP_DIR, ignore_errors=True)


def _safe_name(i: int, filename: str) -> str:
    stem = re.sub(r"[^\w\-]+", "_", Path(filename).stem)[:40] or "file"
    return f"{i:02d}-{stem}{Path(filename).suffix.lower()}"


def build_prompt(ctx: CallContext, instruction: str, focus: str) -> tuple[str, list[tuple[str, Path]], bool]:
    texts, truncated = select_text(ctx.material.texts, focus, config.DOC_CHAR_BUDGET, config.CHUNK_CHARS)
    files = [(_safe_name(i, name), path) for i, (name, path, _) in enumerate(ctx.material.files, 1)]
    parts: list[str] = []
    if texts:
        if truncated:
            parts.append("<note>The documents are too long to include in full. Below are the parts most relevant to this "
                         "request; '[... omitted ...]' marks skipped text.</note>")
        docs = "\n\n".join(f'<document title="{title}">\n{text}\n</document>' for title, text in texts)
        parts.append(f"<documents>\n{docs}\n</documents>")
    if files:
        listing = "\n".join(f"- {fname}: {desc} (uploaded as '{orig}')"
                            for (fname, _), (orig, _, desc) in zip(files, ctx.material.files))
        parts.append("<attached_files>\nThese course files are in your current working folder. Read each one with the Read "
                     f"tool before answering; they are part of the material.\n{listing}\n</attached_files>")
    if ctx.preamble:
        parts.append(ctx.preamble)
    parts.append(instruction.strip())
    parts.append("Respond with ONLY a JSON object that matches the provided JSON schema. No prose before or after it.")
    return "\n\n".join(parts), files, truncated


def record_call(session_id: str | None, purpose: str, model: str, duration_ms: int, ok: bool, error_code: str | None) -> None:
    db.insert("ai_calls", {
        "session_id": session_id, "purpose": purpose, "model": model, "duration_ms": duration_ms,
        "ok": int(ok), "error_code": error_code, "created_at": db.now(),
    })


async def structured_call(
    ctx: CallContext,
    *,
    purpose: str,
    instruction: str,
    schema: dict[str, Any],
    validate: Callable[[dict[str, Any]], T],
    focus: str = "",
    max_tokens: int | None = None,  # kept for signature compatibility; the CLI manages output length
    attempts: int | None = None,
) -> T:
    """Run one schema-constrained request through the CLI and validate the result. On validation
    failure, retry with the validator's message appended (up to VALIDATION_RETRIES retries)."""
    model = ctx.model_smart if config.TASK_TIER.get(purpose) == "smart" else ctx.model_fast
    base_prompt, files, _ = build_prompt(ctx, instruction, focus)
    timeout = config.TASK_TIMEOUT.get(purpose, 300)
    total = attempts or (1 + config.VALIDATION_RETRIES)
    note = ""
    last_error: AppError | None = None
    for attempt in range(total):
        t0 = time.monotonic()
        try:
            data = await run_cli(CliRequest(model=model, prompt=base_prompt + note, schema=schema, files=files, timeout=timeout))
        except AppError as e:
            record_call(ctx.session_id, purpose, model, int((time.monotonic() - t0) * 1000), False, e.code)
            raise
        ms = int(data.get("duration_ms") or (time.monotonic() - t0) * 1000)
        try:
            result = validate(extract_json(data))
        except (ValidationError, ValueError) as e:
            record_call(ctx.session_id, purpose, model, ms, False, "invalid_output")
            log.warning("invalid %s output (attempt %d/%d): %s", purpose, attempt + 1, total, str(e)[:500])
            last_error = AppError("invalid_output", "Claude returned output the app couldn't use.", detail=str(e)[:800])
            note = ("\n\n<previous_attempt_error>\nYour previous response was rejected by the validator:\n"
                    f"{str(e)[:1500]}\nReturn a corrected, complete JSON object.\n</previous_attempt_error>")
            continue
        record_call(ctx.session_id, purpose, model, ms, True, None)
        log.info("claude-cli %s via %s ok in %.1fs", purpose, model, ms / 1000)
        return result
    assert last_error is not None
    raise last_error


# --- Status -----------------------------------------------------------------------------------

_status_cache: tuple[float, dict[str, Any]] | None = None


async def cli_status(refresh: bool = False) -> dict[str, Any]:
    """Whether the CLI is installed and logged in (cached for 60 s)."""
    global _status_cache
    if _status_cache and not refresh and time.time() - _status_cache[0] < 60:
        return _status_cache[1]
    status: dict[str, Any] = {"installed": False, "path": None, "version": None, "logged_in": False,
                              "auth_method": None, "subscription": None, "ready": False, "message": None}
    cli = find_cli()
    if not cli:
        status["message"] = cli_missing_error().message
    else:
        status.update(installed=True, path=cli)
        work = config.LLM_TMP_DIR / "status"
        work.mkdir(parents=True, exist_ok=True)
        try:
            _, out, _ = await _invoke([cli, "--version"], "", work, 30)
            status["version"] = out.strip().splitlines()[0] if out.strip() else None
            _, out, err = await _invoke([cli, "auth", "status", "--json"], "", work, 30)
            info = json.loads(out) if out.strip().startswith("{") else {}
            status.update(
                logged_in=bool(info.get("loggedIn")),
                auth_method=info.get("authMethod"),
                subscription=info.get("subscriptionType"),
            )
            if not status["logged_in"]:
                status["message"] = ("Claude Code is installed but not logged in. Open a terminal, run `claude`, and log in "
                                     "with your Claude account.")
            elif status["auth_method"] not in ("claude.ai", "oauth", "subscription", None):
                status["message"] = (f"Claude Code is logged in with '{status['auth_method']}', not a Claude subscription. "
                                     "Run `claude auth login` to switch to your Pro account.")
        except AppError as e:
            status["message"] = e.message
        except (json.JSONDecodeError, OSError) as e:
            status["message"] = f"Couldn't read Claude Code's login status: {e}"
    status["ready"] = bool(status["installed"] and status["logged_in"])
    _status_cache = (time.time(), status)
    return status
