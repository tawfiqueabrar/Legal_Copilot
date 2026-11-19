import json

import pytest
from pydantic import ValidationError

from app.services.groq import GROQ_API_URL, GroqApiError, GroqCallWrapper
from app.verification.models import SupportVerdict
from conftest import run_inline


class FakeResponse:
    def __init__(self, status_code, body, headers=None):
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}

    def json(self):
        return self.body


def valid_body():
    return {"choices": [{"message": {"content": json.dumps({
        "label": "supports",
        "authority_quote": "This is an exact source sentence that supports this claim.",
        "rationale": "The passage directly states the rule.",
    })}}]}


def test_groq_wrapper_requests_json_and_validates_schema():
    observed = {}

    async def post(url, **kwargs):
        observed.update(url=url, **kwargs)
        return FakeResponse(200, valid_body())

    wrapper = GroqCallWrapper("secret-test-key", default_model="qwen/model", post=post)
    result, model = run_inline(wrapper.generate("Check support", SupportVerdict))

    assert isinstance(result, SupportVerdict)
    assert model == "groq:qwen/model"
    assert observed["url"] == GROQ_API_URL
    assert observed["headers"]["Authorization"] == "Bearer secret-test-key"
    assert observed["json"]["temperature"] == 0
    assert observed["json"]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in observed["json"]["messages"][0]["content"]


def test_groq_wrapper_surfaces_http_status_without_credentials():
    async def post(_url, **_kwargs):
        return FakeResponse(429, {"error": {"message": "rate limit exceeded"}})

    wrapper = GroqCallWrapper("secret-test-key", default_model="qwen/model", post=post)

    with pytest.raises(GroqApiError) as error:
        run_inline(wrapper.generate("prompt", SupportVerdict))

    assert error.value.code == 429
    assert "secret-test-key" not in str(error.value)


def test_groq_wrapper_honors_short_rate_limit_wait_and_retries_once():
    responses = [
        FakeResponse(429, {"error": {"message": "Please try again in 14.76s"}}),
        FakeResponse(200, valid_body()),
    ]
    sleeps = []
    calls = []

    async def post(_url, **_kwargs):
        calls.append(True)
        return responses.pop(0)

    async def sleep(delay):
        sleeps.append(delay)

    wrapper = GroqCallWrapper("key", default_model="qwen/model", post=post, sleep=sleep)
    result, _ = run_inline(wrapper.generate("prompt", SupportVerdict))

    assert isinstance(result, SupportVerdict)
    assert len(calls) == 2
    assert sleeps == [14.76]


def test_groq_wrapper_rejects_invalid_json():
    async def post(_url, **_kwargs):
        return FakeResponse(200, {"choices": [{"message": {"content": "not JSON"}}]})

    wrapper = GroqCallWrapper("key", default_model="qwen/model", post=post)

    with pytest.raises(ValidationError):
        run_inline(wrapper.generate("prompt", SupportVerdict))


def test_groq_wrapper_accepts_image_media_as_inline_data_url():
    observed = {}

    async def post(_url, **kwargs):
        observed.update(kwargs)
        return FakeResponse(200, valid_body())

    wrapper = GroqCallWrapper("key", default_model="qwen/model", post=post)
    run_inline(wrapper.generate("Read this image", SupportVerdict, media=b"image", media_type="image/png"))

    content = observed["json"]["messages"][1]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_groq_wrapper_rejects_pdf_media_instead_of_sending_invalid_payload():
    wrapper = GroqCallWrapper("key", default_model="qwen/model", post=lambda *_args, **_kwargs: pytest.fail("must not send PDF"))

    with pytest.raises(ValueError, match="image files only"):
        run_inline(wrapper.generate("Read this PDF", SupportVerdict, media=b"pdf", media_type="application/pdf"))
