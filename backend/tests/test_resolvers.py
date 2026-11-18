import json
from conftest import run_inline
from app.verification.models import Citation
from app.verification.resolvers import CourtListenerResolver, StaticCorpusResolver, CompositeResolver, build_bank
from app.verification.extract import extract_citations
from app.verification.models import Claim, SupportVerdict
from app.verification.verifier import verify_claim


class Response:
    def __init__(self, payload, status=200): self.payload, self.status_code = payload, status
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError("HTTP error")
    def json(self): return self.payload


class FakeHttp:
    def __init__(self): self.calls = []
    async def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return Response([{"citation":"410 U.S. 113","normalized_citations":["410 U.S. 113"],"status":200,"clusters":[{"case_name":"Roe v. Wade","absolute_url":"/opinion/1/","sub_opinions":[{"resource_uri":"/api/rest/v4/opinions/1/"}]}]}])
    async def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return Response({"plain_text":"Opinion source text."})


def test_courtlistener_resolves_and_fetches_opinion_text():
    http = FakeHttp()
    resolver = CourtListenerResolver(token="test-token", http=http)
    authority = run_inline(resolver.resolve(Citation(kind="us_case", raw="410 U.S. 113", normalized_key="410 U.S. 113")))
    assert authority.title == "Roe v. Wade"
    assert authority.text == "Opinion source text."
    assert authority.status == "resolved"
    assert http.calls[0][1].endswith("/citation-lookup/")


def test_network_error_is_never_resolved():
    class Broken:
        async def post(self, *args, **kwargs): raise OSError("offline")
    resolver = CourtListenerResolver(token="", http=Broken())
    authority = run_inline(resolver.resolve(Citation(kind="us_case", raw="410 U.S. 113", normalized_key="410 U.S. 113")))
    assert authority is None


def test_static_corpus_and_composite_fallback(tmp_path):
    path = tmp_path / "statutes.json"
    path.write_text(json.dumps({"42 U.S.C. § 1983":{"title":"Civil action","url":"https://example.test/1983","text":"official text","retrieved_at":"2026-01-01T00:00:00Z","source":"official"}}), encoding="utf-8")
    citation = Citation(kind="usc", raw="42 U.S.C. § 1983(a)", normalized_key="42 U.S.C. § 1983")
    resolver = StaticCorpusResolver(path)
    authority = run_inline(resolver.resolve(citation))
    assert authority.status == "resolved"
    bank = run_inline(build_bank([citation], CompositeResolver([resolver])))
    assert bank.get("A1").text == "official text"


def test_article_section_corpus_index_excludes_combined_and_empty_entries(tmp_path):
    from app.services.retrieval import BM25EntryIndex

    entries = {
        "EU REGULATION 2016/679": {"title": "Combined", "url": "https://example.test/all", "text": "combined terms", "kind": "eu_regulation"},
        "EU REGULATION 2016/679 ART. 28": {"title": "Processor terms", "url": "https://example.test/a28", "text": "The processor shall protect personal data using appropriate safeguards.", "kind": "eu_regulation", "retrieved_at": "2026-01-01T00:00:00Z"},
        "CAL CIV. CODE § 1798.100": {"title": "Business collection terms", "url": "https://example.test/cal", "text": "A business must provide information about collection and use.", "kind": "cal_civ_code", "retrieved_at": "2026-01-01T00:00:00Z"},
        "CAL CIV. CODE § 1798.140": {"title": "Empty", "url": "https://example.test/empty", "text": None, "kind": "cal_civ_code"},
        "29 U.S.C. § 206": {"title": "Minimum wage", "url": "https://example.test/wage", "text": "An employer shall pay minimum wages for covered work.", "kind": "usc", "retrieved_at": "2026-01-01T00:00:00Z"},
        "15 U.S.C. § 45": {"title": "Trade practices", "url": "https://example.test/trade", "text": "Unfair methods of competition are prohibited.", "kind": "usc", "retrieved_at": "2026-01-01T00:00:00Z"},
    }
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    resolver = StaticCorpusResolver(path)

    records = resolver.article_section_entries()
    matches = BM25EntryIndex(records).search("processor personal data safeguards", min_score=0.01, min_distinct_matches=2)

    assert {row["key"] for row in records} == {"EU REGULATION 2016/679 ART. 28", "CAL CIV. CODE § 1798.100", "29 U.S.C. § 206", "15 U.S.C. § 45"}
    assert matches[0]["entry"]["key"] == "EU REGULATION 2016/679 ART. 28"
    assert matches[0]["score"] > 0
    assert matches[0]["entry"]["text"] == entries[matches[0]["entry"]["key"]]["text"]


def test_bm25_returns_exact_paragraph_chunks_with_locators_and_topic_gate():
    from app.services.retrieval import BM25EntryIndex

    records = [
        {"key": "data authority", "title": "Data processing", "url": "x", "text": "(a) A controller shall document lawful processing and protect personal data.\n(b) The controller shall notify affected people after a breach.", "topic_tags": ["data_protection"], "jurisdictions": ["EU"]},
        {"key": "wage authority", "title": "Wages", "url": "y", "text": "(a) An employer shall pay wages for covered work.\n(b) An employer shall record hours worked.", "topic_tags": ["employment"], "jurisdictions": ["US"]},
    ]
    index = BM25EntryIndex(records)
    hits = index.search("controller protect personal data", top_k=4, min_score=0.01, min_distinct_matches=2, topic_tags={"data_protection"})

    assert hits
    assert all(hit["entry"]["key"] == "data authority" for hit in hits)
    for hit in hits:
        chunk = hit["entry"]
        assert chunk["text"] in records[0]["text"]
        assert chunk["chunk_locator"] in {"(a)", "(b)"}


def test_bm25_relevance_gate_returns_nothing_for_weak_matches():
    from app.services.retrieval import BM25EntryIndex

    records = [
        {"key": "wages", "title": "Employment", "text": "Employer payroll wage hour records.", "topic_tags": ["employment"]},
        {"key": "consumer", "title": "Consumer", "text": "Consumer product information.", "topic_tags": ["consumer_protection"]},
    ]
    index = BM25EntryIndex(records)

    assert index.search("personal data processor breach", topic_tags={"data_protection"}) == []
    assert index.search("payroll", min_score=100, min_distinct_matches=1) == []


def test_real_corpus_chunks_are_exact_slices_and_tagged():
    import json
    from pathlib import Path
    from app.services.retrieval import split_entry_chunks

    backend = Path(__file__).resolve().parents[1]
    corpus = json.loads((backend / "data" / "statutes.json").read_text(encoding="utf-8"))
    tags = json.loads((backend / "data" / "statute_tags.json").read_text(encoding="utf-8"))
    assert set(corpus) == set(tags)
    for key, value in corpus.items():
        if not value.get("text"):
            continue
        chunks = split_entry_chunks({"key": key, **value, **tags[key]})
        assert chunks
        for chunk in chunks:
            assert chunk["text"] in value["text"]
            assert chunk["chunk_locator"]


def _gdpr_corpus():
    return {
        "EU REGULATION 2016/679": {
            "title": "Combined GDPR test entry", "url": "https://example.test/gdpr",
            "source": "test", "kind": "eu_regulation", "text": "Combined dummy text for the whole regulation. " * 3,
            "retrieved_at": "2026-01-01T00:00:00Z",
        },
        "EU REGULATION 2016/679 ART. 28": {
            "title": "Article 28 test entry", "url": "https://example.test/a28",
            "source": "test", "kind": "eu_regulation", "text": "Article 28\nDummy Article 28 text only.",
            "retrieved_at": "2026-01-01T00:00:00Z",
        },
        "EU REGULATION 2016/679 ART. 33": {
            "title": "Article 33 test entry", "url": "https://example.test/a33",
            "source": "test", "kind": "eu_regulation", "text": "Article 33\nDUMMY ARTICLE 33 UNIQUE QUOTE.",
            "retrieved_at": "2026-01-01T00:00:00Z",
        },
        "EU REGULATION 2016/679 ART. 44": {
            "title": "Article 44 test entry", "url": "https://example.test/a44",
            "source": "test", "kind": "eu_regulation", "text": "Article 44\nDummy Article 44 text.",
            "retrieved_at": "2026-01-01T00:00:00Z",
        },
        "EU REGULATION 2016/679 ART. 46": {
            "title": "Article 46 test entry", "url": "https://example.test/a46",
            "source": "test", "kind": "eu_regulation", "text": "Article 46\nDummy Article 46 text.",
            "retrieved_at": "2026-01-01T00:00:00Z",
        },
    }


def _static_resolver(tmp_path, entries=None):
    path = tmp_path / "gdpr-test-corpus.json"
    path.write_text(json.dumps(entries or _gdpr_corpus()), encoding="utf-8")
    return StaticCorpusResolver(path)


def test_article_28_resolution_scopes_checker_and_discards_article_33_quote(tmp_path):
    resolver = _static_resolver(tmp_path)
    citation_candidate = extract_citations("GDPR Article 28")[0]
    citation = Citation(kind=citation_candidate.kind, raw=citation_candidate.raw, normalized_key=citation_candidate.normalized_key)
    authority = run_inline(resolver.resolve(citation))
    seen = []

    async def checker(claim_text, authority_title, authority_text):
        seen.append(authority_text)
        return SupportVerdict(label="supports", authority_quote="DUMMY ARTICLE 33 UNIQUE QUOTE.", rationale="test verdict")

    result = run_inline(verify_claim(
        Claim(claim_id="article-28", text="A test claim.", authority_ids=["A1"], clause_quote="Exact test clause."),
        __import__("app.verification.bank", fromlist=["AuthorityBank"]).AuthorityBank([authority]),
        "Exact test clause.", checker,
    ))
    assert authority.text == "Article 28\nDummy Article 28 text only."
    assert seen == [authority.text]
    assert result.status == "unverified"
    assert result.authority_quotes == []


def test_missing_gdpr_article_does_not_fall_back_to_combined_entry(tmp_path):
    resolver = _static_resolver(tmp_path)
    candidate = extract_citations("GDPR Article 999")[0]
    citation = Citation(kind=candidate.kind, raw=candidate.raw, normalized_key=candidate.normalized_key)
    assert run_inline(resolver.resolve(citation)) is None


def test_articles_44_and_46_resolve_as_separate_entries(tmp_path):
    resolver = _static_resolver(tmp_path)
    candidates = extract_citations("Articles 44 and 46")
    resolved = [
        run_inline(resolver.resolve(Citation(kind=item.kind, raw=item.raw, normalized_key=item.normalized_key)))
        for item in candidates
    ]
    assert [item.key for item in resolved] == [
        "EU REGULATION 2016/679 ART. 44", "EU REGULATION 2016/679 ART. 46"
    ]
    assert [item.text.splitlines()[0] for item in resolved] == ["Article 44", "Article 46"]


def test_whole_gdpr_regulation_is_existence_only_without_combined_text(tmp_path):
    resolver = _static_resolver(tmp_path)
    candidate = extract_citations("Regulation (EU) 2016/679")[0]
    authority = run_inline(resolver.resolve(Citation(kind=candidate.kind, raw=candidate.raw, normalized_key=candidate.normalized_key)))
    assert authority.status == "existence-only"
    assert authority.text is None
