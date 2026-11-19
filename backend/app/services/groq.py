"""Groq OpenAI-compatible chat completion adapter with Pydantic validation."""
from __future__ import annotations

import base64
import json
from typing import Any, Callable, Awaitable

import httpx


GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_TIMEOUT_SECONDS = 60.0


class GroqApiError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        self.code = status_code
        self.message = message
        super().__init__(message)


class GroqCallWrapper:
    """Call Groq using JSON mode, then validate every response with its Pydantic schema."""

    def __init__(
        self,
        api_key: str,
        *,
        default_model: str,
        timeout: float = GROQ_TIMEOUT_SECONDS,
        post: Callable[..., Awaitable[Any]] | None = None,
    ):
        self.api_key = api_key
        self.default_model = default_model
        self.timeout = timeout
        self.post = post

    async def generate(
        self,
        prompt: str,
        schema: type,
        model: str | None = None,
        *,
        media: bytes | None = None,
        media_type: str | None = None,
    ) -> tuple[Any, str]:
        selected_model = (model or self.default_model).strip()
        schema_text = schema.model_json_schema()
        system_message = (
            "Return one JSON object that validates against this JSON Schema. "
            "Do not include markdown or text outside the object.\nJSON Schema:\n"
            + json.dumps(schema_text, ensure_ascii=False)
        )
        user_content: Any = prompt
        if media is not None:
            if not media_type or not media_type.startswith("image/"):
                raise ValueError("The selected Groq vision route accepts image files only; OCR the PDF or upload its page images.")
            encoded = base64.b64encode(media).decode("ascii")
            user_content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}},
            ]
        payload = {
            "model": selected_model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_content},
            ],
            # Groq documents temperature 0 as near-zero sampling; the app still
            # requests zero for analytical steps. Pydantic rejects schema drift.
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if self.post:
            response = await self.post(GROQ_API_URL, headers=headers, json=payload, timeout=self.timeout)
        else:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(GROQ_API_URL, headers=headers, json=payload)
        if response.status_code >= 400:
            message = "Groq request failed."
            try:
                body = response.json()
                message = str(body.get("error", {}).get("message") or body.get("message") or message)
            except Exception:
                pass
            raise GroqApiError(response.status_code, message[:1200])
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Groq returned an empty structured response.")
        result = schema.model_validate_json(content)
        return result, f"groq:{selected_model}"
