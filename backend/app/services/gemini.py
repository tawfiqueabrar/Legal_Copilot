"""Shared Gemini client, retry policy, structured decoding, and safe error details."""
from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any

from google import genai
from google.genai import types


RETRY_DELAYS = (1.0,)
RETRYABLE_STATUSES = {429, 503, 504}
REQUEST_TIMEOUT_SECONDS = 60.0
_SCHEMA_KEYS_UNSUPPORTED_BY_GEMINI = {"$defs", "definitions", "$ref", "additionalProperties", "default", "examples"}


def build_gemini_client(api_key: str):
    """Create a client with an explicit request deadline and no SDK retries."""
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=60_000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


def http_status(exc: BaseException) -> int | None:
    for value in (getattr(exc, "code", None), getattr(exc, "status_code", None), getattr(getattr(exc, "response", None), "status_code", None)):
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def gemini_response_schema(schema: type) -> dict[str, Any]:
    """Inline Pydantic refs and remove JSON-Schema keywords Gemini rejects."""
    source = schema.model_json_schema()
    definitions = source.get("$defs", source.get("definitions", {}))

    def clean(value: Any, resolving: frozenset[str] = frozenset()) -> Any:
        if isinstance(value, list):
            return [clean(item, resolving) for item in value]
        if not isinstance(value, dict):
            return value
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            name = reference.rsplit("/", 1)[-1]
            if name in resolving:
                raise ValueError(f"Recursive output schema is unsupported by Gemini: {name}")
            if name not in definitions:
                raise ValueError(f"Unresolved Pydantic output schema reference: {reference}")
            expanded = clean(definitions[name], resolving | {name})
            siblings = {key: item for key, item in value.items() if key != "$ref"}
            if siblings:
                expanded.update(clean(siblings, resolving))
            return expanded
        return {
            key: clean(item, resolving)
            for key, item in value.items()
            if key not in _SCHEMA_KEYS_UNSUPPORTED_BY_GEMINI
        }

    return clean(source)


def gemini_error_details(
    exc: BaseException,
    *,
    api_key: str = "",
    provider_name: str = "Gemini",
) -> dict[str, Any]:
    """Return a UI-safe diagnostic without exposing the configured credential."""
    status = http_status(exc)
    raw_message = getattr(exc, "message", None) or str(exc) or "No provider message was supplied."
    message = str(raw_message)
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    # Defensive scrub in case the SDK includes the credential in a URL or payload.
    message = re.sub(r"(?i)(key\s*[=:]\s*)[^\s&,]+", r"\1[REDACTED]", message)
    name = type(exc).__name__
    lowered = message.casefold()
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or "timeout" in name.casefold() or status == 504:
        category = "timeout"
    elif status == 429 or "resource_exhausted" in lowered or "rate limit" in lowered:
        category = "rate_limited"
    elif status == 503 or "overloaded" in lowered or "service unavailable" in lowered:
        category = "overloaded"
    elif status == 404 or "model not found" in lowered or "not_found" in lowered:
        category = "model_not_found"
    elif status == 401 or "api_key_invalid" in lowered or "invalid api key" in lowered or "api key not valid" in lowered:
        category = "key_invalid"
    elif status == 403:
        category = "key_invalid_or_access_denied"
    else:
        category = "provider_error"
    details = {
        "provider": provider_name,
        "category": category,
        "exception_class": name,
        "http_status": status,
        "message": message,
    }
    attempted_models = getattr(exc, "attempted_models", None)
    if isinstance(attempted_models, list) and attempted_models:
        details["attempted_models"] = [str(model) for model in attempted_models]
    return details


class GeminiCallWrapper:
    """One structured Gemini call path with a short retry and bounded model failover."""

    def __init__(
        self,
        client: Any,
        *,
        fallback_model: str = "",
        fallback_models: list[str] | None = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ):
        self.client = client
        candidates = fallback_models if fallback_models is not None else [fallback_model]
        self.fallback_models = list(dict.fromkeys(
            candidate.strip() for candidate in candidates
            if candidate and candidate.strip()
        ))
        self.sleep = sleep

    async def _attempts(
        self,
        model: str,
        prompt: str,
        schema: type,
        *,
        media: bytes | None,
        media_type: str | None,
        retry: bool,
    ) -> Any:
        delays = RETRY_DELAYS if retry else ()
        for attempt in range(len(delays) + 1):
            try:
                response = await self.client.aio.models.generate_content(
                    model=model,
                    contents=[prompt, types.Part.from_bytes(data=media, mime_type=media_type)] if media and media_type else prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        response_mime_type="application/json",
                        response_schema=gemini_response_schema(schema),
                    ),
                )
                return schema.model_validate_json(response.text or "{}")
            except Exception as exc:
                status = http_status(exc)
                # Quota and overload errors are unlikely to recover on an
                # immediate repeat. If backups exist, preserve latency by
                # trying them instead of spending time retrying this model.
                if attempt >= len(delays) or status not in RETRYABLE_STATUSES or (status in {429, 503, 504} and self.fallback_models):
                    raise
                await self.sleep(delays[attempt])
        raise RuntimeError("Gemini retry loop ended unexpectedly")

    async def generate(
        self,
        prompt: str,
        schema: type,
        model: str,
        *,
        media: bytes | None = None,
        media_type: str | None = None,
    ) -> tuple[Any, str]:
        attempted = [model]
        try:
            value = await self._attempts(model, prompt, schema, media=media, media_type=media_type, retry=True)
            return value, model
        except Exception as exc:
            primary_exception = exc
            recoverable = http_status(exc) in {429, 503, 504} or isinstance(
                exc, (TimeoutError, asyncio.TimeoutError)
            )
            if not recoverable:
                raise

        last_error = primary_exception
        for fallback in self.fallback_models:
            if fallback == model:
                continue
            attempted.append(fallback)
            try:
                # Each backup is attempted once. Do not add another backoff wait
                # after the primary has already exhausted its short retry.
                value = await self._attempts(fallback, prompt, schema, media=media, media_type=media_type, retry=False)
                return value, fallback
            except Exception as fallback_error:
                last_error = fallback_error
                status = http_status(fallback_error)
                if status in {401, 403}:
                    break  # Credential/access failures affect every model.
                if status == 504 or isinstance(fallback_error, (TimeoutError, asyncio.TimeoutError)):
                    # A second model timing out is a strong signal that this
                    # request cannot finish within the current deadline. Stop
                    # here rather than spending another full timeout on a third model.
                    break
                if status in {429, 404, 503, 504} or isinstance(fallback_error, (TimeoutError, asyncio.TimeoutError)):
                    continue
                break
        try:
            last_error.attempted_models = attempted
        except Exception:
            pass
        raise last_error
