import json
import sys

from scripts import set_statute_text


def run_with_temp_corpus(monkeypatch, tmp_path, corpus, needle, text):
    data_path = tmp_path / "statutes.json"
    data_path.write_text(json.dumps(corpus), encoding="utf-8")
    text_path = tmp_path / "source.txt"
    text_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(set_statute_text, "DATA", data_path)
    monkeypatch.setattr(sys, "argv", ["set_statute_text.py", needle, str(text_path)])
    result = set_statute_text.main()
    return result, json.loads(data_path.read_text(encoding="utf-8"))


def test_unique_match_loads_text_into_only_matching_key(monkeypatch, tmp_path):
    dummy_text = "Dummy test-only source text. " * 5
    result, data = run_with_temp_corpus(
        monkeypatch,
        tmp_path,
        {"CAL BUS. & PROF. CODE § 16600": {"text": None}, "CAL BUS. & PROF. CODE § 16600.5": {"text": None}},
        "16600",
        dummy_text,
    )
    assert result == 0
    assert data["CAL BUS. & PROF. CODE § 16600"]["text"] == dummy_text.strip()
    assert data["CAL BUS. & PROF. CODE § 16600"]["retrieved_at"]
    assert data["CAL BUS. & PROF. CODE § 16600.5"]["text"] is None


def test_16600_does_not_match_16600_5(monkeypatch, tmp_path, capsys):
    result, _ = run_with_temp_corpus(
        monkeypatch,
        tmp_path,
        {"CAL BUS. & PROF. CODE § 16600.5": {"text": None}},
        "16600",
        "Dummy test-only source text. " * 5,
    )
    assert result == 1
    assert "matched 0 keys" in capsys.readouterr().out


def test_text_under_80_characters_is_refused(monkeypatch, tmp_path, capsys):
    corpus_path = tmp_path / "statutes.json"
    corpus_path.write_text(json.dumps({"CAL BUS. & PROF. CODE § 16600": {"text": None}}), encoding="utf-8")
    text_path = tmp_path / "short.txt"
    text_path.write_text("dummy text", encoding="utf-8")
    monkeypatch.setattr(set_statute_text, "DATA", corpus_path)
    monkeypatch.setattr(sys, "argv", ["set_statute_text.py", "16600", str(text_path)])
    assert set_statute_text.main() == 1
    assert "Refusing" in capsys.readouterr().out
    assert json.loads(corpus_path.read_text(encoding="utf-8"))["CAL BUS. & PROF. CODE § 16600"]["text"] is None


def test_zero_matches_fail(monkeypatch, tmp_path, capsys):
    result, _ = run_with_temp_corpus(
        monkeypatch,
        tmp_path,
        {"CAL BUS. & PROF. CODE § 16600": {"text": None}},
        "missing",
        "Dummy test-only source text. " * 5,
    )
    assert result == 1
    assert "matched 0 keys" in capsys.readouterr().out


def test_multiple_matches_fail(monkeypatch, tmp_path, capsys):
    result, _ = run_with_temp_corpus(
        monkeypatch,
        tmp_path,
        {"CAL BUS. & PROF. CODE § 16600": {"text": None}, "OTHER § 16600": {"text": None}},
        "16600",
        "Dummy test-only source text. " * 5,
    )
    assert result == 1
    assert "matched 2 keys" in capsys.readouterr().out
