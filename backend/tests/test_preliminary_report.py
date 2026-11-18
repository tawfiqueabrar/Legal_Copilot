import pytest

from app.services.preliminary_report import build_preliminary_report


def base_inputs(**overrides):
    data = {
        "document_name": "review.txt",
        "document_text": "9.3 Liability. The clause may change risk allocation. California and GDPR are referenced.",
        "clauses": [{"id": "C1", "heading": "9.3 Liability", "text": "9.3 Liability. The clause may change risk allocation."}],
        "risks": [{
            "risk_id": "risk-1", "title": "Potential cap interaction", "severity": "medium",
            "clause_ids": ["C1"], "exact_quotes": ["The clause may change risk allocation."],
            "why_non_obvious": "This may matter if the stated trigger occurs.",
            "jurisdiction_assumption": "Jurisdiction needs confirmation.",
            "suggested_mitigation_clause": "Clarify the scope of this term.", "search_queries": [], "authority_ids": [],
        }],
        "authority_bank": [], "claims": [], "draft_claims": [], "removed_claims": [],
        "jurisdiction": {"governing_law": "Unclear", "venue": "Unclear", "data_subject_regions": [], "party_locations": [], "gap": None},
    }
    data.update(overrides)
    return build_preliminary_report(**data)


def test_header_fields_are_computed_from_document_and_loaded_bank_sources():
    loaded = {"id": "A1", "key": "synthetic:loaded", "kind": "us_case", "title": "Synthetic resolver record", "source": "test resolver", "url": "https://example.test/record", "text": "Synthetic source payload for this test.", "retrieved_at": "2026-01-01T00:00:00Z", "status": "resolved"}
    empty = {"id": "A2", "key": "synthetic:empty", "kind": "us_case", "title": "Empty resolver record", "source": "test resolver", "url": "https://example.test/empty", "text": None, "retrieved_at": None, "status": "existence-only"}
    report = base_inputs(authority_bank=[loaded, empty])
    assert report["document_name"] == "review.txt"
    assert report["assessment_line"] == "Potential risks found; no legal violation established"
    assert [source.authority_id for source in report["legal_sources_in_scope"]] == ["A1"]
    assert any(item.name == "California law" for item in report["not_assessed"])
    assert all("source library lacks loaded text" in item.note for item in report["not_assessed"])


def test_foreign_regime_applicability_is_conditional_and_uk_gdpr_is_not_assessed():
    authority = {
        "id": "A1", "key": "EU REGULATION 2016/679 ART. 28", "kind": "eu_regulation",
        "title": "Synthetic Article 28 resolver record", "source": "test resolver",
        "url": "https://example.test/record", "text": "Synthetic resolver payload for this report test.",
        "retrieved_at": "2026-01-01T00:00:00Z", "status": "resolved",
    }
    report = base_inputs(
        document_text="The agreement uses Delaware law. A party is organized in England and Wales. GDPR Article 28 and UK GDPR are referenced.",
        authority_bank=[authority],
        risks=[{
            "risk_id": "foreign-regime", "title": "Potential cross-border applicability question", "severity": "medium",
            "clause_ids": ["C1"], "exact_quotes": ["The clause may change risk allocation."],
            "why_non_obvious": "This may depend on facts and governing law.",
            "jurisdiction_assumption": "Applicability conditional.", "suggested_mitigation_clause": "Confirm the applicable regime.",
            "search_queries": ["GDPR Article 28"], "authority_ids": ["A1"],
        }],
        jurisdiction={"governing_law": "Delaware", "venue": "Unclear", "party_locations": ["England and Wales"], "data_subject_regions": [], "subject_hints": [], "gap": None},
    )
    risk = report["risks"][0]
    assert "applicability conditional" in risk.applicability_note.casefold()
    assert any(item.name == "UK GDPR" for item in report["not_assessed"])


def test_absent_gdpr_article_text_is_source_not_loaded_and_unverified():
    authority = {"id": "A1", "key": "EU REGULATION 2016/679", "kind": "eu_regulation", "title": "Regulation source", "source": "EUR-Lex", "url": "https://eur-lex.europa.eu/source", "text": "Article 28\nProcessor\nLoaded text only for this article.", "retrieved_at": "2026-01-01T00:00:00Z", "status": "resolved"}
    draft_claim = {"claim_id": "M1", "text": "A proposition about GDPR Article 33 [A1].", "authority_ids": ["A1"], "clause_quote": "The clause may change risk allocation."}
    claim = {**draft_claim, "result": {"claim_id": "M1", "status": "verified", "reasons": [], "authority_quotes": ["Loaded text only for this article."]}}
    report = base_inputs(
        document_text="9.3 Liability. The clause may change risk allocation. GDPR Article 33 may be relevant.",
        authority_bank=[authority],
        claims=[claim],
        draft_claims=[draft_claim],
        risks=[{
            "risk_id": "gdpr-risk", "title": "Potential notice timing issue", "severity": "high",
            "clause_ids": ["C1"], "exact_quotes": ["The clause may change risk allocation."],
            "why_non_obvious": "This may matter if a notification duty applies.",
            "jurisdiction_assumption": "Applicability conditional.", "suggested_mitigation_clause": "Clarify the notice process.",
                "search_queries": ["GDPR Article 33 notification scope"], "authority_ids": ["A1"],
        }],
    )
    risk = report["risks"][0]
    assert risk.source_not_loaded is True
    assert risk.citation_status == "unverified"
    assert "Source not loaded" in risk.citation_check_line
    assert risk.legal_references == []
    assert any(item.name == "GDPR Article 33" for item in report["not_assessed"])
    assert report["excluded_claim_ids"] == ["M1"]


def test_fabricated_quote_is_rejected_from_report():
    report = base_inputs(risks=[{
        "risk_id": "fake", "title": "Potential risk", "severity": "medium", "clause_ids": ["C1"],
        "exact_quotes": ["This text does not occur in the contract."], "why_non_obvious": "This may matter if true.",
        "jurisdiction_assumption": "Unclear", "suggested_mitigation_clause": "Review the term.",
        "search_queries": [], "authority_ids": [],
    }])
    assert report["risks"] == []


def test_risk_reference_outside_authority_bank_is_unverified_and_source_not_loaded():
    report = base_inputs(risks=[{
        "risk_id": "missing-authority", "title": "Potential source review", "severity": "medium", "clause_ids": ["C1"],
        "exact_quotes": ["The clause may change risk allocation."], "why_non_obvious": "This may affect risk allocation.",
        "jurisdiction_assumption": "Unclear", "suggested_mitigation_clause": "Clarify the term.",
        "search_queries": ["Research relevant governing law"], "authority_ids": ["A9"],
    }])
    risk = report["risks"][0]
    assert risk.source_not_loaded is True
    assert risk.citation_status == "unverified"
    assert "Source not loaded" in risk.citation_check_line
    assert risk.legal_references == []


def test_redaction_marker_creates_evidence_gap_and_links_finding():
    report = base_inputs(
        document_text="9.3 Liability. [REDACTED] The clause may change risk allocation.",
        clauses=[{"id": "C1", "heading": "9.3 Liability", "text": "9.3 Liability. [REDACTED] The clause may change risk allocation."}],
    )
    assert len(report["evidence_gaps"]) == 1
    assert report["evidence_gaps"][0].marker == "[REDACTED]"
    assert report["evidence_gaps"][0].affected_risk_ids == ["risk-1"]


@pytest.mark.parametrize("status,label", [
    ("verified", "Verified"),
    ("existence_only", "Existence-only"),
    ("unverified", "Unverified"),
    ("rejected", "Rejected"),
])
def test_citation_check_line_uses_backend_status_label(status, label):
    authority = {"id": "A1", "key": "synthetic:source", "kind": "us_case", "title": "Synthetic resolver record", "source": "test resolver", "url": "https://example.test/source", "text": "Synthetic source payload for this test.", "retrieved_at": "2026-01-01T00:00:00Z", "status": "resolved"}
    memo_claim = {"claim_id": "M1", "text": "A test proposition.", "authority_ids": ["A1"], "clause_quote": "The clause may change risk allocation.", "result": {"claim_id": "M1", "status": status, "reasons": [], "authority_quotes": []}}
    draft_claim = {key: memo_claim[key] for key in ("claim_id", "text", "authority_ids", "clause_quote")}
    overrides = {
        "authority_bank": [authority],
        "risks": [{**base_inputs()["risks"][0].model_dump(exclude={"contract_evidence", "legal_references"}), "authority_ids": ["A1"]}],
        "claims": [] if status == "rejected" else [memo_claim],
        "draft_claims": [draft_claim],
        "removed_claims": [{"claim_id": "M1", "status": "rejected", "reasons": []}] if status == "rejected" else [],
    }
    report = base_inputs(**overrides)
    line = report["risks"][0].citation_check_line
    assert report["risks"][0].citation_status == status
    assert line.startswith(f"Citation check: {label} —")
