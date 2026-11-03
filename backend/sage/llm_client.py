"""The only module that talks to the AI: it runs the locally installed Claude Code CLI (`claude -p`)
as an async subprocess, using the user's Claude subscription login.

Every call:
  * strips ANTHROPIC_* and third-party-provider variables from the child environment, so the CLI can
    never fall back to API-key billing;
  * disables MCP servers, user/project settings (hooks, permissions), slash commands, and every built-in
    tool. Calls that include images or scanned PDFs get only the Read tool, confined (--restricted) to a
    temp folder holding copies of those files. Video searches without a YouTube API key get only the
    WebSearch tool (and no files); their tool results are captured so the app can check that every
    returned link really came from the search;
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
    tools: list[str] = field(default_factory=list)  # extra built-in tools (only "WebSearch" is used)


# --- Environment & discovery --------------------------------------------------------------

def child_env() -> dict[str, str]:
    return {
        k: v for k, v in os.environ.items()
        if not k.upper().startswith(STRIP_ENV_PREFIXES) and k.upper() not in STRIP_ENV_NAMES
    }


def _prefer_native(path: str) -> str:
    """npm's claude.cmd runs through cmd.exe, which mangles JSON arguments and cuts long command lines; the
    package holds the real binary next to it."""
    if path.lower().endswith(".cmd"):
        native = Path(path).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if native.is_file():
            return str(native)
    return path


def _from_login_shell() -> str | None:
    """Apps opened from the macOS Finder or a Linux menu get a minimal PATH; the user's shell knows better."""
    shell = os.environ.get("SHELL")
    if sys.platform == "win32" or not shell:
        return None
    try:
        out = subprocess.run([shell, "-lc", "command -v claude"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    last = out.splitlines()[-1] if out else ""
    return last if last.startswith("/") and Path(last).is_file() else None


def find_cli() -> str | None:
    found = shutil.which("claude")
    if found:
        return _prefer_native(found)
    home = Path.home()
    exe = "claude.exe" if sys.platform == "win32" else "claude"
    candidates = [
        home / ".local" / "bin" / exe,
        home / ".claude" / "local" / exe,
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / exe,
        Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd",
        home / ".npm-global" / "bin" / exe,
        Path("/usr/local/bin/claude"),
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/bin/claude"),
    ]
    found = next((str(c) for c in candidates if c.is_file()), None)
    return _prefer_native(found) if found else _from_login_shell()


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
        f"Claude Code isn't installed, or this app can't find it. Follow Anthropic's install instructions at "
        f"{config.CLAUDE_CODE_DOCS_URL}, then run `claude` once in a terminal and sign in with your Claude account.",
    )


ALLOWED_EXTRA_TOOLS = {"WebSearch"}


def build_args(cli: str, req: CliRequest) -> list[str]:
    extra = [t for t in req.tools if t in ALLOWED_EXTRA_TOOLS]
    tools = (["Read"] if req.files else []) + extra
    args = [
        cli, "-p",
        # Calls with WebSearch stream every event so the search results themselves can be inspected.
        *(["--output-format", "stream-json", "--verbose"] if extra else ["--output-format", "json"]),
        "--model", req.model,
        "--system-prompt", req.system,
        "--json-schema", json.dumps(req.schema, separators=(",", ":")),
        "--tools", ",".join(tools),
        "--restricted",                    # no shell/code tools; file tools confined to the work folder
        "--permission-prompts", "none",    # anything that would need approval is denied
        "--strict-mcp-config",             # ignore the user's MCP servers
        "--setting-sources", "",           # ignore user/project settings (hooks, permissions)
        "--disable-slash-commands",
        "--no-session-persistence",
    ]
    if extra:
        args += ["--allowedTools", ",".join(extra)]  # WebSearch needs approval, and nobody is there to give it
    return args


def tool_results(stdout: str, tool: str) -> list[str]:
    """Text of every result returned by `tool` in a stream-json transcript."""
    names: dict[str, str] = {}
    out: list[str] = []
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict) or ev.get("type") not in ("assistant", "user"):
            continue
        for block in (ev.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                names[block.get("id", "")] = block.get("name", "")
            elif block.get("type") == "tool_result" and names.get(block.get("tool_use_id", "")) == tool \
                    and not block.get("is_error"):
                content = block.get("content")
                if isinstance(content, list):
                    content = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
                out.append(str(content or ""))
    return out


# --- Error classification ---------------------------------------------------------------------

_USAGE = re.compile(r"usage limit|limit reached|hit your (?:usage |session |weekly )?limit|limit (?:will )?reset|"
                    r"out of (?:extra )?usage|rate[ _-]?limit|too many requests|\b429\b", re.I)
_LOGIN = re.compile(r"not logged in|please (?:run )?/login|run `?claude`? (?:to|and) log ?in|log ?in (?:again|required)|"
                    r"invalid api key|authentication|unauthori[sz]ed|oauth token|credentials|\b401\b", re.I)
_OVERLOADED = re.compile(r"overloaded|\b529\b", re.I)
_NETWORK = re.compile(r"ENOTFOUND|EAI_AGAIN|ECONNREFUSED|ECONNRESET|ETIMEDOUT|getaddrinfo|network (?:error|is unreachable)|"
                      r"connection (?:error|refused|timed out)|fetch failed|unable to connect|could not resolve", re.I)
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
    if _NETWORK.search(blob):
        return AppError("network", "Claude Code couldn't reach the internet. Check your connection and try again.", detail=text[:300])
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
        data = parse_result(code, out, err)
        if "WebSearch" in req.tools:
            data["_search_results"] = tool_results(out, "WebSearch")
        return data
    finally:
        shutil.rmtree(work, ignore_errors=True)


def cleanup_tmp() -> None:
    """Remove work folders left behind by a crash."""
    shutil.rmtree(config.LLM_TMP_DIR, ignore_errors=True)


def _safe_name(i: int, filename: str) -> str:
    stem = re.sub(r"[^\w\-]+", "_", Path(filename).stem)[:40] or "file"
    return f"{i:02d}-{stem}{Path(filename).suffix.lower()}"


def build_prompt(ctx: CallContext, instruction: str, focus: str, doc_budget: int | None = None) -> tuple[str, list[tuple[str, Path]], bool]:
    texts, truncated = select_text(ctx.material.texts, focus, doc_budget or config.DOC_CHAR_BUDGET, config.CHUNK_CHARS)
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
    doc_budget: int | None = None,  # inline document characters; defaults to DOC_CHAR_BUDGET
) -> T:
    """Run one schema-constrained request through the CLI and validate the result. On validation
    failure, retry with the validator's message appended (up to VALIDATION_RETRIES retries)."""
    base_prompt, files, _ = build_prompt(ctx, instruction, focus, doc_budget)
    return await _run_validated(ctx, purpose, base_prompt, files, schema, lambda obj, _data: validate(obj), attempts)


async def search_call(
    ctx: CallContext,
    *,
    purpose: str,
    instruction: str,
    schema: dict[str, Any],
    validate: Callable[[dict[str, Any], list[str]], T],
    system: str,
    attempts: int | None = None,
) -> T:
    """A request that may only use the CLI's WebSearch tool (no course material, no files). `validate`
    receives the JSON result and the text of every search result, so it can reject anything that
    didn't come from the search."""
    prompt = instruction.strip() + "\n\nRespond with ONLY a JSON object that matches the provided JSON schema. No prose before or after it."
    return await _run_validated(ctx, purpose, prompt, [], schema,
                                lambda obj, data: validate(obj, data.get("_search_results") or []),
                                attempts, tools=["WebSearch"], system=system)


async def _run_validated(
    ctx: CallContext, purpose: str, base_prompt: str, files: list[tuple[str, Path]], schema: dict[str, Any],
    validate: Callable[[dict[str, Any], dict[str, Any]], T], attempts: int | None,
    tools: list[str] | None = None, system: str = SYSTEM_PROMPT,
) -> T:
    model = ctx.model_smart if config.TASK_TIER.get(purpose) == "smart" else ctx.model_fast
    timeout = config.TASK_TIMEOUT.get(purpose, 300)
    total = attempts or (1 + config.VALIDATION_RETRIES)
    note = ""
    last_error: AppError | None = None
    for attempt in range(total):
        t0 = time.monotonic()
        try:
            data = await run_cli(CliRequest(model=model, prompt=base_prompt + note, schema=schema, files=files,
                                            timeout=timeout, system=system, tools=list(tools or [])))
        except AppError as e:
            record_call(ctx.session_id, purpose, model, int((time.monotonic() - t0) * 1000), False, e.code)
            raise
        ms = int(data.get("duration_ms") or (time.monotonic() - t0) * 1000)
        try:
            result = validate(extract_json(data), data)
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
                                     "Run `claude auth login` to switch to your Claude account.")
        except AppError as e:
            status["message"] = e.message
        except (json.JSONDecodeError, OSError) as e:
            status["message"] = f"Couldn't read Claude Code's login status: {e}"
    status["ready"] = bool(status["installed"] and status["logged_in"])
    _status_cache = (time.time(), status)
    return status
