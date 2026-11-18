import pytest
from pydantic import ValidationError

from app.services import gemini
from app.services.gemini import GeminiCallWrapper, RETRY_DELAYS, build_gemini_client, gemini_error_details, gemini_response_schema
from app.agents.risk_models import RiskScan
from app.verification.models import SupportVerdict
from conftest import run_inline


class ApiFailure(Exception):
    def __init__(self, code, message="provider failure"):
        self.code = code
        self.message = message
        super().__init__(message)


class Response:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.calls = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        value = self.sequence.pop(0)
        if isinstance(value, BaseException):
            raise value
        return Response(value)


class FakeClient:
    def __init__(self, sequence):
        self.aio = type("Aio", (), {})()
        self.aio.models = FakeModels(sequence)


def payload(rationale="grounded"):
    return '{"label":"supports","authority_quote":"exact source span","rationale":"' + rationale + '"}'


def test_503_then_success_retries_and_validates_structured_schema():
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)

    client = FakeClient([ApiFailure(503), payload()])
    wrapper = GeminiCallWrapper(client, fallback_model="fallback", sleep=sleep)
    value, actual = run_inline(wrapper.generate("prompt", SupportVerdict, "primary"))

    assert actual == "primary"
    assert value == SupportVerdict(label="supports", authority_quote="exact source span", rationale="grounded")
    assert sleeps == [RETRY_DELAYS[0]]
    assert all(call["config"].temperature == 0.0 for call in client.aio.models.calls)
    assert all(call["config"].response_schema["properties"]["label"]["enum"] for call in client.aio.models.calls)
    assert all("additionalProperties" not in call["config"].response_schema for call in client.aio.models.calls)


def test_pydantic_nested_schema_is_inlined_and_gemini_unsupported_keywords_removed():
    schema = gemini_response_schema(RiskScan)

    assert "$defs" not in schema
    assert "risks" in schema["properties"]
    assert "additionalProperties" not in str(schema)
    assert "$ref" not in str(schema)


def test_primary_503s_then_fallback_is_tried_once():
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)

    client = FakeClient([ApiFailure(503)] * 4 + [ApiFailure(503, "fallback overloaded")])
    wrapper = GeminiCallWrapper(client, fallback_model="fallback", sleep=sleep)

    with pytest.raises(ApiFailure) as error:
        run_inline(wrapper.generate("prompt", SupportVerdict, "primary"))

    assert error.value.code == 503
    assert [call["model"] for call in client.aio.models.calls] == ["primary"] * 4 + ["fallback"]
    assert sleeps == list(RETRY_DELAYS)


def test_successful_fallback_is_reported_as_the_model_used():
    async def sleep(_delay):
        return None

    client = FakeClient([ApiFailure(503)] * 4 + [payload()])
    wrapper = GeminiCallWrapper(client, fallback_model="fallback", sleep=sleep)

    value, actual = run_inline(wrapper.generate("prompt", SupportVerdict, "primary"))

    assert isinstance(value, SupportVerdict)
    assert actual == "fallback"


def test_404_is_not_retried_or_fallbacked():
    client = FakeClient([ApiFailure(404, "model not found")])
    wrapper = GeminiCallWrapper(client, fallback_model="fallback", sleep=lambda _: pytest.fail("unexpected retry"))

    with pytest.raises(ApiFailure):
        run_inline(wrapper.generate("prompt", SupportVerdict, "primary"))

    assert len(client.aio.models.calls) == 1
    assert client.aio.models.calls[0]["model"] == "primary"


def test_invalid_json_is_rejected_without_retry():
    client = FakeClient(["not json"])
    wrapper = GeminiCallWrapper(client, fallback_model="fallback", sleep=lambda _: pytest.fail("unexpected retry"))

    with pytest.raises(ValidationError):
        run_inline(wrapper.generate("prompt", SupportVerdict, "primary"))

    assert len(client.aio.models.calls) == 1


def test_error_details_classify_and_redact_credential():
    details = gemini_error_details(ApiFailure(401, "invalid api key secret-value"), api_key="secret-value")

    assert details == {
        "category": "key_invalid",
        "exception_class": "ApiFailure",
        "http_status": 401,
        "message": "invalid api key [REDACTED]",
    }


def test_client_has_60_second_timeout_and_sdk_internal_retries_disabled(monkeypatch):
    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(gemini.genai, "Client", fake_client)

    build_gemini_client("dummy-key")

    options = captured["http_options"]
    assert options.timeout == 60_000
    assert options.retry_options.attempts == 1


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (ApiFailure(401, "API_KEY_INVALID"), "key_invalid"),
        (ApiFailure(404, "model not found"), "model_not_found"),
        (ApiFailure(503, "overloaded"), "overloaded"),
        (ApiFailure(429, "rate limit exceeded"), "rate_limited"),
        (TimeoutError("deadline exceeded"), "timeout"),
    ],
)
def test_provider_error_categories_are_distinguished(error, category):
    assert gemini_error_details(error)["category"] == category
