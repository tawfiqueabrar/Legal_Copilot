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
    assert metrics["cross_clause_recall"]["value"] == 1.0
    assert metrics["quote_grounding_rate"]["value"] == 1.0
