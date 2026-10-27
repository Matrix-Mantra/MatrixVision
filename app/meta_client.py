"""Meta Model API client (OpenAI-compatible, https://api.meta.ai/v1).

Retries follow dev.meta.ai/docs/error-handling: back off on 429/500/503 (respecting Retry-After),
never retry 400/401/402/403/404/413, and don't blindly retry 504. If a Muse Spark version stays
unavailable, the next version in MUSE_SPARK_MODELS is tried.
"""

from __future__ import annotations

import logging
import random
import time
from functools import lru_cache
from typing import Any, Callable

import httpx
import openai
from openai import OpenAI

from . import config

log = logging.getLogger("vision.meta")

RETRYABLE = {429, 500, 503}
# Errors where another model version might work (overloaded/missing/forbidden for this model).
FALLBACK = RETRYABLE | {403, 404, 504}


class NotConfigured(RuntimeError):
    """META_API_KEY is not set."""


def configured() -> bool:
    return bool(config.META_API_KEY)


@lru_cache(maxsize=1)
def client() -> OpenAI:
    if not configured():
        raise NotConfigured("META_API_KEY is not set")
    # The SDK's own retries are off: we retry here so we can fall back between models.
    return OpenAI(base_url=config.META_API_BASE, api_key=config.META_API_KEY,
                  timeout=config.META_TIMEOUT_SECONDS, max_retries=0)


def status_of(exc: BaseException) -> int | None:
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code
    if isinstance(exc, httpx.HTTPStatusError):  # endpoints called without the SDK (speech)
        return exc.response.status_code
    if isinstance(exc, httpx.TimeoutException):
        return 504
    if isinstance(exc, httpx.TransportError):
        return 503
    if isinstance(exc, openai.APITimeoutError):
        return 504
    if isinstance(exc, openai.APIConnectionError):
        return 503
    return None


def is_busy(exc: BaseException) -> bool:
    return status_of(exc) in RETRYABLE | {504}


def _retry_after(exc: BaseException) -> float | None:
    resp = getattr(exc, "response", None)
    try:
        return float(resp.headers.get("retry-after")) if resp is not None else None
    except (TypeError, ValueError):
        return None


def _backoff(attempt: int, exc: BaseException) -> float:
    delay = 0.5 * (2 ** attempt) * (0.75 + random.random() / 2)  # 500 ms, doubling, with jitter
    ra = _retry_after(exc)
    if ra is not None:
        delay = max(delay, ra)
    return delay


def call_with_fallback(models: list[str], fn: Callable[[str], Any], *,
                       max_retries: int | None = None, max_wait: float = 8.0,
                       sleep: Callable[[float], None] | None = None) -> tuple[Any, str]:
    """Run fn(model) for each model in turn until one succeeds. Returns (result, model_used).

    A Retry-After longer than max_wait moves on to the next model instead of waiting.
    """
    retries = config.META_MAX_RETRIES if max_retries is None else max_retries
    last: BaseException | None = None
    for model in models:
        for attempt in range(retries + 1):
            try:
                return fn(model), model
            except Exception as exc:  # noqa: BLE001 - classified below
                last = exc
                code = status_of(exc)
                log.warning("meta call failed model=%s attempt=%s status=%s", model, attempt, code)
                if code not in RETRYABLE or attempt == retries:
                    break
                delay = _backoff(attempt, exc)
                if delay > max_wait:
                    break
                (sleep or time.sleep)(delay)
        if status_of(last) not in FALLBACK and not isinstance(last, ValueError):
            # Our request is wrong (400/401/402/413...): another model won't fix it.
            raise last
    assert last is not None
    raise last


def output_text(response: Any) -> str:
    """The text of a Responses API result: output[] -> message -> content[] -> output_text."""
    text = getattr(response, "output_text", None)
    if text:
        return text
    parts = []
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) == "message":
            for c in getattr(item, "content", None) or []:
                if getattr(c, "type", None) == "output_text":
                    parts.append(c.text)
    return "".join(parts)
