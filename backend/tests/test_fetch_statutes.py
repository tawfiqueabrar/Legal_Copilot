import json

from scripts import fetch_statutes


class Headers:
    def get_content_charset(self):
        return "utf-8"


class FakeResponse:
    headers = Headers()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b"<html><body><h1>Section</h1><p>Downloaded source text " + b"x" * 200 + b"</p></body></html>"


def test_fetch_text_extracts_downloaded_html_and_timestamp():
    text, retrieved_at = fetch_statutes.fetch_text("https://www.govinfo.gov/example", opener=lambda *a, **kw: FakeResponse())
    assert "Downloaded source text" in text
    assert retrieved_at.endswith("Z")


def test_failed_fetch_writes_null_and_warns(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(fetch_statutes, "OUTPUT", tmp_path / "statutes.json")

    def fail(_url):
        raise OSError("offline")

    monkeypatch.setattr(fetch_statutes, "fetch_text", fail)
    assert fetch_statutes.main() == 0
    captured = capsys.readouterr()
    corpus = json.loads((tmp_path / "statutes.json").read_text(encoding="utf-8"))
    assert "WARNING: could not fetch" in captured.err
    assert all(entry["text"] is None and entry["retrieved_at"] is None for entry in corpus.values())
