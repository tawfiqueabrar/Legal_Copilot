from pathlib import Path

from app.config import BACKEND_ENV_FILE, Settings


def test_default_env_file_is_absolute_and_relative_to_backend():
    assert Path(BACKEND_ENV_FILE).is_absolute()
    assert Path(BACKEND_ENV_FILE) == Path(__file__).resolve().parents[1] / ".env"


def test_default_gemini_model_is_a_current_supported_model(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    configured = Settings(_env_file=None)

    assert configured.gemini_model == "gemini-3.8-flash"


def test_gemini_and_courtlistener_variables_are_loaded_from_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEMINI_API_KEY=dummy-gemini-key\nGEMINI_MODEL=dummy-analysis-model\n"
        "GEMINI_FALLBACK_MODEL=dummy-fallback-model\nSUPPORT_CHECK_MODEL=dummy-checker-model\n"
        "COURTLISTENER_TOKEN=dummy-courtlistener-token\n",
        encoding="utf-8",
    )

    configured = Settings(_env_file=env_file)

    assert configured.gemini_api_key == "dummy-gemini-key"
    assert configured.gemini_model == "dummy-analysis-model"
    assert configured.gemini_fallback_model == "dummy-fallback-model"
    assert configured.support_check_model == "dummy-checker-model"
    assert configured.courtlistener_token == "dummy-courtlistener-token"


def test_fallback_model_defaults_to_lightweight_backup(monkeypatch):
    monkeypatch.delenv("GEMINI_FALLBACK_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_SECONDARY_FALLBACK_MODEL", raising=False)
    configured = Settings(_env_file=None, _env_ignore_empty=True)

    assert configured.gemini_fallback_model == "gemini-3.1-flash-lite"
    assert configured.gemini_secondary_fallback_model == "gemini-3.5-flash"
    assert configured.gemini_fallback_models == ["gemini-3.1-flash-lite", "gemini-3.5-flash"]


def test_support_check_model_defaults_to_analysis_model(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_MODEL=analysis-model\n", encoding="utf-8")

    configured = Settings(_env_file=env_file)

    assert configured.support_check_model == "analysis-model"
