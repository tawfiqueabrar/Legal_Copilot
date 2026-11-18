import json
from pathlib import Path

from app.verification.extract import extract_citations


BACKEND = Path(__file__).resolve().parents[1]


def test_every_seed_key_exists_in_static_corpus():
    corpus = json.loads((BACKEND / "data" / "statutes.json").read_text(encoding="utf-8"))
    seed_citations = [
        "Regulation (EU) 2016/679", "Cal. Bus. & Prof. Code § 16600",
        "Cal. Bus. & Prof. Code § 16600.5", "29 U.S.C. § 206", "29 U.S.C. § 207",
        "15 U.S.C. § 45", "18 U.S.C. § 1836", "Cal. Civ. Code § 1798.100",
        "Cal. Civ. Code § 1798.140",
    ]
    normalized = {candidate.normalized_key for raw in seed_citations for candidate in extract_citations(raw)}
    # Article-scoped GDPR entries may extend the seed corpus independently.
    assert normalized <= set(corpus)
    assert all({"title", "url", "text", "retrieved_at"} <= entry.keys() for entry in corpus.values())


def test_static_resolver_defaults_to_backend_data_corpus():
    from app.verification.resolvers import StaticCorpusResolver

    assert StaticCorpusResolver().path == BACKEND / "data" / "statutes.json"
