"""Thin wrapper around the Anthropic SDK.

Every call in a session sends: [system prompt] + [documents..., material preamble <- cache breakpoint]
+ [task instruction]. Model and effort are pinned per session (changing either invalidates the
cache), and output is constrained with structured outputs, then validated with Pydantic."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

import anthropic
from pydantic import ValidationError

from . import config, db, keystore
from .errors import AppError
from .prompts.system import SYSTEM_PROMPT

log = logging.getLogger(__name__)
T = TypeVar("T")

_client: anthropic.AsyncAnthropic | None = None
_client_key: str | None = None
_semaphore: asyncio.Semaphore | None = None
_semaphore_loop: asyncio.AbstractEventLoop | None = None
MAX_CONCURRENT_CALLS = 4


def get_client() -> anthropic.AsyncAnthropic:
    global _client, _client_key
    key, _ = keystore.get_api_key()
    if not key:
        raise AppError("missing_key", "No Anthropic API key is set. Add one in Settings.")
    if _client is None or key != _client_key:
        _client = anthropic.AsyncAnthropic(api_key=key, max_retries=3, timeout=600.0)
        _client_key = key
    return _client


def _sem() -> asyncio.Semaphore:
    global _semaphore, _semaphore_loop
    loop = asyncio.get_running_loop()
    if _semaphore is None or _semaphore_loop is not loop:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT_CALLS)
        _semaphore_loop = loop
    return _semaphore


@dataclass
class CallContext:
    session_id: str | None
    model: str
    effort: str
    fallback: bool
    prefix_blocks: list[dict[str, Any]] = field(default_factory=list)


# --- Cost ---------------------------------------------------------------------------

def price_for(model: str) -> dict[str, float]:
    for known, price in config.PRICING.items():
        if model == known or model.startswith(known):
            return price
    return config.PRICING[config.DEFAULT_MODEL]


def compute_cost(model: str, input_tokens: int, output_tokens: int, write_5m: int, write_1h: int, read: int) -> float:
    p = price_for(model)
    cost = (
        input_tokens * p["input"]
        + output_tokens * p["output"]
        + write_5m * p["input"] * config.CACHE_WRITE_5M_MULT
        + write_1h * p["input"] * config.CACHE_WRITE_1H_MULT
        + read * p["cache_read"]
    )
    return cost / 1_000_000


def record_usage(session_id: str | None, purpose: str, message: Any) -> dict[str, Any]:
    u = message.usage
    cc = getattr(u, "cache_creation", None)
    w5 = getattr(cc, "ephemeral_5m_input_tokens", 0) or 0 if cc else 0
    w1h = getattr(cc, "ephemeral_1h_input_tokens", 0) or 0 if cc else 0
    if not cc:
        w5 = getattr(u, "cache_creation_input_tokens", 0) or 0
    read = getattr(u, "cache_read_input_tokens", 0) or 0
    row = {
        "session_id": session_id,
        "purpose": purpose,
        "model": message.model,
        "input_tokens": u.input_tokens or 0,
        "output_tokens": u.output_tokens or 0,
        "cache_write_5m": w5,
        "cache_write_1h": w1h,
        "cache_read": read,
        "cost_usd": compute_cost(message.model, u.input_tokens or 0, u.output_tokens or 0, w5, w1h, read),
        "request_id": getattr(message, "_request_id", None),
        "created_at": db.now(),
    }
    db.insert("api_calls", row)
    log.info("claude %s %s in=%s out=%s w1h=%s read=%s $%.4f", purpose, message.model,
             row["input_tokens"], row["output_tokens"], w1h, read, row["cost_usd"])
    return row


# --- Error mapping -----------------------------------------------------------------

def map_error(e: Exception) -> AppError:
    if isinstance(e, AppError):
        return e
    if isinstance(e, anthropic.AuthenticationError):
        return AppError("invalid_key", "Your Anthropic API key was rejected. Check it in Settings.")
    if isinstance(e, anthropic.PermissionDeniedError):
        return AppError("permission_denied", "This API key doesn't have permission to use the selected model.", detail=str(e.message))
    if isinstance(e, anthropic.NotFoundError):
        return AppError("model_not_found", "The selected model isn't available to this API key. Pick another model in Settings.", detail=str(e.message))
    if isinstance(e, anthropic.RateLimitError):
        retry = None
        try:
            retry = float(e.response.headers.get("retry-after", "")) or None
        except (TypeError, ValueError):
            pass
        wait = f" Try again in about {int(retry)} seconds." if retry else " Wait a minute and try again."
        return AppError("rate_limited", "You've hit the API rate limit." + wait, retry_after=retry)
    if isinstance(e, anthropic.BadRequestError):
        msg = str(e.message)
        if "credit balance" in msg.lower() or "billing" in msg.lower():
            return AppError("billing", "Your Anthropic account is out of credits. Add credits in the Anthropic Console.", detail=msg)
        if "too large" in msg.lower() or "too long" in msg.lower() or "pages" in msg.lower():
            return AppError("file_too_large", "The uploaded material is too large for one request. Remove some files or pages.", detail=msg)
        return AppError("bad_request", "The API rejected the request.", detail=msg)
    if isinstance(e, anthropic.APITimeoutError):
        return AppError("timeout", "The request to Claude timed out. Try again.")
    if isinstance(e, anthropic.APIConnectionError):
        return AppError("network", "Couldn't reach the Anthropic API. Check your internet connection.")
    if isinstance(e, anthropic.APIStatusError):
        if e.status_code == 529:
            return AppError("overloaded", "Claude is temporarily overloaded. Try again in a moment.")
        if e.status_code >= 500:
            return AppError("server_error", "The Anthropic API had a server error. Try again in a moment.", detail=str(e.message))
        return AppError("bad_request", "The API rejected the request.", detail=str(e.message))
    log.exception("unexpected error calling Claude", exc_info=e)
    return AppError("server_error", "Something went wrong while talking to Claude.", detail=repr(e))


# --- Calls ----------------------------------------------------------------------------

def build_params(ctx: CallContext, instruction: str, schema: dict[str, Any], max_tokens: int) -> dict[str, Any]:
    params: dict[str, Any] = {
        "model": ctx.model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": SYSTEM_PROMPT}],
        "messages": [{"role": "user", "content": [*ctx.prefix_blocks, {"type": "text", "text": instruction}]}],
        "output_config": {"effort": ctx.effort, "format": {"type": "json_schema", "schema": schema}},
    }
    if ctx.fallback and ctx.model in config.FALLBACK_MODELS:
        params["betas"] = [config.FALLBACK_BETA]
        params["fallbacks"] = "default"
    return params


async def _send(params: dict[str, Any]) -> Any:
    client = get_client()
    async with _sem():
        if "betas" in params:
            async with client.beta.messages.stream(**params) as stream:
                return await stream.get_final_message()
        async with client.messages.stream(**params) as stream:
            return await stream.get_final_message()


def _text_of(message: Any) -> str:
    return "".join(b.text for b in message.content if getattr(b, "type", None) == "text")


async def structured_call(
    ctx: CallContext,
    *,
    purpose: str,
    instruction: str,
    schema: dict[str, Any],
    validate: Callable[[dict[str, Any]], T],
    max_tokens: int = 32000,
    attempts: int = 2,
) -> T:
    """Run a structured-output call and validate it. On validation failure or truncation, retry
    with the validator's message appended after the cached prefix."""
    if not keystore.get_api_key()[0]:
        raise AppError("missing_key", "No Anthropic API key is set. Add one in Settings.")
    note = ""
    last_error: AppError | None = None
    for attempt in range(attempts):
        params = build_params(ctx, instruction + note, schema, max_tokens)
        try:
            message = await _send(params)
        except Exception as e:  # noqa: BLE001 - mapped to a typed AppError
            raise map_error(e) from e
        record_usage(ctx.session_id, purpose, message)

        if message.stop_reason == "refusal":
            raise AppError(
                "refusal",
                "Claude declined to process this request. If your material is legitimate course content, "
                "try rephrasing the coverage request or removing unrelated files.",
            )
        if message.stop_reason == "max_tokens":
            last_error = AppError("truncated", "Claude's response was cut off before it finished.")
            max_tokens = min(max_tokens * 2, 64000)
            note = "\n\nYour previous response was cut off. Keep text fields concise."
            continue
        text = _text_of(message)
        try:
            return validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            log.warning("invalid %s output (attempt %d): %s", purpose, attempt + 1, e)
            last_error = AppError("invalid_output", "Claude returned output the app couldn't use.", detail=str(e)[:800])
            note = (
                "\n\nYour previous response was rejected by the validator with this error:\n"
                f"{str(e)[:1500]}\nReturn a corrected, complete response."
            )
    assert last_error is not None
    raise last_error


async def check_key(model: str) -> None:
    """Validates the stored key cheaply (Models API, no tokens billed)."""
    try:
        await get_client().models.retrieve(model)
    except Exception as e:  # noqa: BLE001
        raise map_error(e) from e
