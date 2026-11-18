from app.api import verify as verify_api
from app.verification.models import Authority
from conftest import run_inline


class MissingResolver:
    async def resolve(self, citation):
        return None


class PresentResolver:
    async def resolve(self, citation):
        return Authority(
            id="A1", key=citation.normalized_key, kind=citation.kind,
            title="Source record", source="test", url="https://example.test/source",
            text="Source text that is real within this isolated test." * 4,
            retrieved_at="2026-01-01T00:00:00Z", status="resolved",
        )


def test_unresolved_fabricated_citation_is_never_verified(monkeypatch):
    monkeypatch.setattr(verify_api.workflow, "resolver", MissingResolver())
    result = run_inline(verify_api.verify_citation(verify_api.CitationProbeRequest(citation="999 U.S. 999")))
    assert result.result.status in {"rejected", "unverified"}
    assert result.result.status != "verified"
    assert result.authority is None


def test_source_lookup_alone_never_marks_citation_verified(monkeypatch):
    monkeypatch.setattr(verify_api.workflow, "resolver", PresentResolver())
    result = run_inline(verify_api.verify_citation(verify_api.CitationProbeRequest(citation="410 U.S. 113")))
    assert result.result.status == "unverified"
    assert result.result.status != "verified"


def test_unsupported_input_is_rejected():
    result = run_inline(verify_api.verify_citation(verify_api.CitationProbeRequest(citation="999 999")))
    assert result.result.status == "rejected"


def test_missing_gdpr_article_abstains_as_source_not_loaded(monkeypatch):
    monkeypatch.setattr(verify_api.workflow, "resolver", MissingResolver())
    result = run_inline(verify_api.verify_citation(verify_api.CitationProbeRequest(citation="GDPR Article 999")))
    assert result.normalized_key == "EU REGULATION 2016/679 ART. 999"
    assert result.result.status == "unverified"
    assert any("Source not loaded" in reason for reason in result.result.reasons)
    assert result.result.status != "verified"
