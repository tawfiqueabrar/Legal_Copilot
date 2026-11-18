import json
import re
from pathlib import Path
import sys

from scripts import add_statute


KEY = "EU REGULATION 2016/679 ART. 33"
DUMMY_TEXT = "Dummy test-only source text. " * 5


def invoke(monkeypatch, tmp_path, corpus, text, *, replace=False):
    data_path = tmp_path / "statutes.json"
    data_path.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
    text_path = tmp_path / "dummy.txt"
    text_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(add_statute, "DATA", data_path)
    argv = [
        "add_statute.py", "--key", KEY, "--title", "Dummy test title",
        "--url", "https://example.test/dummy", "--source", "test source",
        "--kind", "eu_regulation", "--text-file", str(text_path),
    ]
    if replace:
        argv.append("--replace")
    monkeypatch.setattr(sys, "argv", argv)
    result = add_statute.main()
    return result, data_path, json.loads(data_path.read_text(encoding="utf-8"))


def test_successful_add_writes_entry_fields_and_utc_timestamp(monkeypatch, tmp_path):
    result, _, data = invoke(monkeypatch, tmp_path, {"EXISTING KEY": {"text": "kept"}}, DUMMY_TEXT)
    assert result == 0
    assert data[KEY] == {
        "title": "Dummy test title",
        "url": "https://example.test/dummy",
        "source": "test source",
        "kind": "eu_regulation",
        "text": DUMMY_TEXT.strip(),
        "retrieved_at": data[KEY]["retrieved_at"],
    }
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", data[KEY]["retrieved_at"])
    assert data["EXISTING KEY"] == {"text": "kept"}


def test_duplicate_key_is_refused_without_replace(monkeypatch, tmp_path, capsys):
    existing = {"title": "Old title", "text": "Existing dummy text."}
    result, _, data = invoke(monkeypatch, tmp_path, {KEY: existing}, DUMMY_TEXT)
    assert result == 1
    assert data[KEY] == existing
    assert "key already exists" in capsys.readouterr().out


def test_replace_overwrites_existing_key(monkeypatch, tmp_path):
    existing = {"title": "Old title", "text": "Existing dummy text."}
    result, _, data = invoke(monkeypatch, tmp_path, {KEY: existing}, DUMMY_TEXT, replace=True)
    assert result == 0
    assert data[KEY]["title"] == "Dummy test title"
    assert data[KEY]["text"] == DUMMY_TEXT.strip()
    assert data[KEY]["source"] == "test source"
    assert set(data[KEY]) == {"title", "url", "source", "kind", "text", "retrieved_at"}


def test_short_text_is_refused_without_modifying_corpus(monkeypatch, tmp_path, capsys):
    corpus = {"EXISTING KEY": {"text": "preserved"}}
    result, _, data = invoke(monkeypatch, tmp_path, corpus, "short dummy")
    assert result == 1
    assert data == corpus
    assert "at least 80" in capsys.readouterr().out
