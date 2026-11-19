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


def test_503_switches_to_fallback_immediately_and_validates_schema():
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)

    client = FakeClient([ApiFailure(503), payload()])
    wrapper = GeminiCallWrapper(client, fallback_model="fallback", sleep=sleep)
    value, actual = run_inline(wrapper.generate("prompt", SupportVerdict, "primary"))

    assert actual == "fallback"
    assert value == SupportVerdict(label="supports", authority_quote="exact source span", rationale="grounded")
    assert sleeps == []
    assert all(call["config"].temperature == 0.0 for call in client.aio.models.calls)
    assert all(call["config"].response_schema["properties"]["label"]["enum"] for call in client.aio.models.calls)
    assert all("additionalProperties" not in call["config"].response_schema for call in client.aio.models.calls)


def test_429_switches_to_fallback_immediately():
    async def sleep(_delay):
        pytest.fail("quota errors should fail over immediately when a backup exists")

    client = FakeClient([ApiFailure(429, "daily quota exceeded"), payload()])
    wrapper = GeminiCallWrapper(client, fallback_model="fallback", sleep=sleep)

    value, actual = run_inline(wrapper.generate("prompt", SupportVerdict, "primary"))

    assert isinstance(value, SupportVerdict)
    assert actual == "fallback"
    assert [call["model"] for call in client.aio.models.calls] == ["primary", "fallback"]


def test_429_on_all_models_reports_attempted_models():
    async def sleep(_delay):
        pytest.fail("quota errors should fail over immediately when backups exist")

    client = FakeClient([ApiFailure(429, "daily quota exceeded")] * 3)
    wrapper = GeminiCallWrapper(client, fallback_models=["fallback", "secondary"], sleep=sleep)

    with pytest.raises(ApiFailure) as error:
        run_inline(wrapper.generate("prompt", SupportVerdict, "primary"))

    assert [call["model"] for call in client.aio.models.calls] == ["primary", "fallback", "secondary"]
    assert error.value.attempted_models == ["primary", "fallback", "secondary"]


def test_504_switches_to_fallback_without_waiting_on_same_model():
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)

    client = FakeClient([ApiFailure(504), payload()])
    wrapper = GeminiCallWrapper(client, fallback_model="fallback", sleep=sleep)

    _, actual = run_inline(wrapper.generate("prompt", SupportVerdict, "primary"))

    assert actual == "fallback"
    assert len(client.aio.models.calls) == 2
    assert [call["model"] for call in client.aio.models.calls] == ["primary", "fallback"]
    assert sleeps == []


def test_timeout_on_fallback_stops_before_a_third_model():
    client = FakeClient([ApiFailure(504), ApiFailure(504), payload()])
    wrapper = GeminiCallWrapper(client, fallback_models=["fallback", "secondary"])

    with pytest.raises(ApiFailure) as error:
        run_inline(wrapper.generate("prompt", SupportVerdict, "primary"))

    assert [call["model"] for call in client.aio.models.calls] == ["primary", "fallback"]
    assert error.value.attempted_models == ["primary", "fallback"]


def test_pydantic_nested_schema_is_inlined_and_gemini_unsupported_keywords_removed():
    schema = gemini_response_schema(RiskScan)

    assert "$defs" not in schema
    assert "risks" in schema["properties"]
    assert "additionalProperties" not in str(schema)
    assert "$ref" not in str(schema)


def test_primary_503s_then_fallback_chain_is_tried_once_per_model():
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)

    client = FakeClient([ApiFailure(503)] * 3)
    wrapper = GeminiCallWrapper(client, fallback_models=["fallback", "secondary"], sleep=sleep)

    with pytest.raises(ApiFailure) as error:
        run_inline(wrapper.generate("prompt", SupportVerdict, "primary"))

    assert error.value.code == 503
    assert [call["model"] for call in client.aio.models.calls] == ["primary", "fallback", "secondary"]
    assert sleeps == []
    assert error.value.attempted_models == ["primary", "fallback", "secondary"]
    assert gemini_error_details(error.value)["attempted_models"] == ["primary", "fallback", "secondary"]


def test_successful_fallback_is_reported_as_the_model_used():
    async def sleep(_delay):
        return None

    client = FakeClient([ApiFailure(503), payload()])
    wrapper = GeminiCallWrapper(client, fallback_model="fallback", sleep=sleep)

    value, actual = run_inline(wrapper.generate("prompt", SupportVerdict, "primary"))

    assert isinstance(value, SupportVerdict)
    assert actual == "fallback"


def test_second_fallback_recovers_after_first_backup_is_overloaded():
    async def sleep(_delay):
        return None

    client = FakeClient([ApiFailure(503)] * 2 + [payload()])
    wrapper = GeminiCallWrapper(client, fallback_models=["lite", "secondary"], sleep=sleep)

    value, actual = run_inline(wrapper.generate("prompt", SupportVerdict, "primary"))

    assert isinstance(value, SupportVerdict)
    assert actual == "secondary"
    assert [call["model"] for call in client.aio.models.calls] == ["primary", "lite", "secondary"]


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
        "provider": "Gemini",
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
