"""Shared Gemini client, retry policy, structured decoding, and safe error details."""
from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any

from google import genai
from google.genai import types


RETRY_DELAYS = (2.0, 5.0, 10.0)
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


def gemini_error_details(exc: BaseException, *, api_key: str = "") -> dict[str, Any]:
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
    return {
        "category": category,
        "exception_class": name,
        "http_status": status,
        "message": message,
    }


class GeminiCallWrapper:
    """One structured Gemini call path with explicit retry and fallback behavior."""

    def __init__(
        self,
        client: Any,
        *,
        fallback_model: str = "",
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        request_timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
    ):
        self.client = client
        self.fallback_model = fallback_model.strip()
        self.sleep = sleep
        self.request_timeout_seconds = request_timeout_seconds

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
                if attempt >= len(delays) or status not in RETRYABLE_STATUSES:
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
        try:
            value = await self._attempts(model, prompt, schema, media=media, media_type=media_type, retry=True)
            return value, model
        except Exception as exc:
            if http_status(exc) not in {503, 504} or not self.fallback_model or self.fallback_model == model:
                raise
        # A fallback is deliberately a single request; no recursive fallback chain.
        value = await self._attempts(self.fallback_model, prompt, schema, media=media, media_type=media_type, retry=False)
        return value, self.fallback_model
