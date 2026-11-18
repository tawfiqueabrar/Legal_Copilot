import json
from pathlib import Path

from scripts.evaluate import _document_expectation_checks, _risk_diagnostics


ROOT = Path(__file__).resolve().parents[2]


def test_all_planted_sections_and_quote_anchors_are_in_demo_contract():
    expected = json.loads((ROOT / "demo" / "expected_risks.json").read_text(encoding="utf-8"))
    source = (ROOT / "demo" / "sample_msa.txt").read_text(encoding="utf-8")

    checks = _document_expectation_checks(expected, source)

    assert len(checks) == len(expected["planted_risks"])
    assert all(item["all_sections_found"] for item in checks)
    assert all(item["expected_quote_found_verbatim"] for item in checks)


def test_risk_diagnostics_keep_rule_and_report_closest_candidate():
    expected = {"planted_risks": [{"id": "r1", "title": "fixture", "sections": ["7.1"], "quote": "exact anchor", "cross_clause": False}]}
    memo = {
        "clauses": [{"id": "C1", "heading": "7.1 DATA", "text": "The clause has exact anchor text."}],
        "risks": [{"risk_id": "found", "title": "candidate", "clause_ids": ["C1"], "exact_quotes": ["The clause has exact anchor text."]}],
    }

    matched, _, section_matched, diagnostics = _risk_diagnostics(memo, expected, "The clause has exact anchor text.")

    assert matched == {"r1"}
    assert section_matched == {"r1"}
    assert diagnostics[0]["closest_reported_risk"]["risk_id"] == "found"
    assert diagnostics[0]["closest_reported_risk"]["quote_anchor_overlap"] is True
