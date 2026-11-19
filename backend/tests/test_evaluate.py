from scripts.evaluate import _fabrication_check, _status_from_memo
from conftest import run_inline


def test_fabricated_citation_closed_set_check_is_not_verified():
    result = run_inline(_fabrication_check())
    assert result == {"status": "passed", "result_status": "rejected"}


def test_eval_matching_requires_section_and_quote_overlap():
    expected = {"planted_risks": [{"id": "planted", "sections": ["9.3", "9.4"], "quote": "indemnity obligations", "cross_clause": True}]}
    memo = {
        "clauses": [
            {"id": "C1", "heading": "9.3 Liability cap", "text": "The cap applies."},
            {"id": "C2", "heading": "9.4 Indemnity", "text": "Indemnity obligations remain outside it."},
        ],
        "risks": [{"clause_ids": ["C1", "C2"], "exact_quotes": ["Indemnity obligations remain outside it."]}],
        "authority_bank": [], "claims": [],
    }
    metrics = _status_from_memo(memo, expected, "The cap applies. Indemnity obligations remain outside it.")
    assert metrics["risk_recall"]["value"] == 1.0
    assert metrics["section_match_recall"]["value"] == 1.0
    assert metrics["cross_clause_recall"]["value"] == 1.0
    assert metrics["quote_grounding_rate"]["value"] == 1.0


def test_section_match_recall_does_not_require_quote_anchor_and_authorities_are_distinct():
    expected = {"planted_risks": [{"id": "planted", "sections": ["2.2"], "quote": "the planted quote"}]}
    memo = {
        "clauses": [{"id": "C1", "heading": "2.2 Changes", "text": "A different grounded quotation."}],
        "risks": [{"clause_ids": ["C1"], "exact_quotes": ["A different grounded quotation."]}],
        "authority_bank": [{"id": "A1"}],
        "claims": [
            {"authority_ids": ["A1", "A2"], "result": {"status": "verified"}},
            {"authority_ids": ["A1"], "result": {"status": "existence_only"}},
        ],
    }
    metrics = _status_from_memo(memo, expected, "A different grounded quotation.")
    assert metrics["section_match_recall"]["value"] == 1.0
    assert metrics["risk_recall"]["value"] == 0.0
    assert metrics["distinct_authority_precision"]["distinct_authorities_cited"] == 2
    assert metrics["distinct_authority_precision"]["distinct_authorities_found_in_bank"] == 1
    assert metrics["distinct_authority_precision"]["value"] == 0.5


def test_per_claim_outcomes_use_recorded_checker_calls_not_text_availability_guess():
    expected = {"planted_risks": []}
    memo = {
        "clauses": [], "risks": [],
        "authority_bank": [{"id": "A1", "key": "source-key", "title": "Source title", "text": "Loaded authority passage."}],
        "claims": [{"claim_id": "M1", "text": "A narrow claim.", "authority_ids": ["A1"], "result": {"status": "unverified", "reasons": ["Quote not grounded."], "authority_quotes": []}}],
        "analysis_metadata": {"support_checks": [{
            "claim": "A narrow claim.", "authority_title": "Source title", "label": "supports",
            "support_quote": "Non-verbatim checker response.", "quote_verbatim": False,
        }]},
    }
    metrics = _status_from_memo(memo, expected, "")
    claim = metrics["per_claim_support_checks"][0]
    authority = metrics["per_authority_claim_outcomes"][0]

    assert claim["support_checker_called"] is True
    assert authority["support_checker_called"] is True
    assert authority["support_quote"] == "Non-verbatim checker response."
    assert authority["support_quote_verbatim"] is False
    assert claim["status"] == "unverified"
