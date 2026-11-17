"""Evaluate the real Legal Copilot pipeline when configured; otherwise run safe offline checks.

Usage from repo root: ``python backend/scripts/evaluate.py``.
Uploaded/demo content is read only for this explicit evaluation command. Results contain
metrics and blocked reasons, not document text.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402
from app.ingestion import ingest_document  # noqa: E402
from app.verification.bank import AuthorityBank  # noqa: E402
from app.verification.extract import extract_citations, span_in_text  # noqa: E402
from app.verification.models import Claim  # noqa: E402
from app.verification.resolvers import StaticCorpusResolver  # noqa: E402
from app.verification.verifier import verify_claim  # noqa: E402

DEMO = ROOT / "demo" / "sample_msa.txt"
EXPECTED = ROOT / "demo" / "expected_risks.json"
CORPUS = BACKEND / "data" / "statutes.json"
OUTPUT = BACKEND / "eval_results.json"
BLOCKED = "BLOCKED: statute text not loaded"


def _status(value: str, *, metric: str) -> dict[str, Any]:
    return {"value": None, "status": value, "metric": metric}


def _status_from_memo(memo: dict, expected: dict, source: str) -> dict[str, Any]:
    clauses = {clause["id"]: clause for clause in memo.get("clauses", [])}
    risks = memo.get("risks", [])
    matched: set[str] = set()
    cross_matched: set[str] = set()
    all_quotes = [quote for risk in risks for quote in risk.get("exact_quotes", [])]
    grounded_quotes = sum(1 for quote in all_quotes if span_in_text(quote, source))

    for planted in expected["planted_risks"]:
        section_set = set(planted["sections"])
        for risk in risks:
            risk_sections: set[str] = set()
            for clause_id in risk.get("clause_ids", []):
                clause = clauses.get(clause_id)
                if not clause:
                    continue
                heading = clause.get("heading") or ""
                import re
                for match in re.finditer(r"(?<!\d)(\d+(?:\.\d+)+)\b", heading + "\n" + clause.get("text", "")[:160]):
                    risk_sections.add(match.group(1))
            section_overlap = section_set.intersection(risk_sections)
            quote_overlap = any(span_in_text(planted["quote"], quote) for quote in risk.get("exact_quotes", []))
            if section_overlap and quote_overlap:
                matched.add(planted["id"])
                if planted.get("cross_clause") and len(set(risk.get("clause_ids", []))) >= 2:
                    cross_matched.add(planted["id"])
                break

    authorities = {item.get("id"): item for item in memo.get("authority_bank", [])}
    eligible_ids: list[str] = []
    for claim in memo.get("claims", []):
        if (claim.get("result") or {}).get("status") in {"verified", "existence_only"}:
            eligible_ids.extend(claim.get("authority_ids", []))
    citation_precision = sum(1 for authority_id in eligible_ids if authority_id in authorities) / len(eligible_ids) if eligible_ids else None
    claims = memo.get("claims", [])
    claim_verification = sum(1 for claim in claims if (claim.get("result") or {}).get("status") == "verified") / len(claims) if claims else None
    cross_total = sum(1 for risk in expected["planted_risks"] if risk.get("cross_clause"))
    return {
        "risk_recall": {"value": len(matched) / len(expected["planted_risks"]) if expected["planted_risks"] else None, "matched": len(matched), "total": len(expected["planted_risks"]), "status": "completed"},
        "cross_clause_recall": {"value": len(cross_matched) / cross_total if cross_total else None, "matched": len(cross_matched), "total": cross_total, "status": "completed"},
        "quote_grounding_rate": {"value": grounded_quotes / len(all_quotes) if all_quotes else None, "grounded": grounded_quotes, "total": len(all_quotes), "status": "completed"},
        "citation_precision": {"value": citation_precision, "resolved_bank_authorities": sum(1 for authority_id in eligible_ids if authority_id in authorities), "total_cited_authorities": len(eligible_ids), "status": "completed" if eligible_ids else "not run: no eligible citation claims"},
        "claim_verification_rate": {"value": claim_verification, "verified": sum(1 for claim in claims if (claim.get("result") or {}).get("status") == "verified"), "total": len(claims), "status": "completed" if claims else "not run: no memo claims"},
    }


async def _fabrication_check() -> dict[str, Any]:
    citation_text = "999 U.S. 999"
    candidates = extract_citations(citation_text)
    resolver = StaticCorpusResolver(CORPUS)
    resolved = await resolver.resolve(
        __import__("app.verification.models", fromlist=["Citation"]).Citation(
            kind=candidates[0].kind, raw=candidates[0].raw, normalized_key=candidates[0].normalized_key
        )
    ) if candidates else None
    # A disconnected or missing source must never be elevated. Run the actual closed-set verifier.
    bank = AuthorityBank([resolved] if resolved else [])
    claim = Claim(claim_id="fabrication-probe", text="The supplied citation supports the proposition.", authority_ids=["A1"], clause_quote=citation_text)
    async def no_support(*_args):
        from app.verification.models import SupportVerdict
        return SupportVerdict(label="not_supported", rationale="Offline fabrication probe has no support evidence.")
    result = await verify_claim(claim, bank, citation_text, no_support)
    return {"status": "passed" if result.status != "verified" else "failed", "result_status": result.status}


async def evaluate() -> dict[str, Any]:
    source = DEMO.read_text(encoding="utf-8")
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    corpus = json.loads(CORPUS.read_text(encoding="utf-8")) if CORPUS.exists() else {}
    needed_statute_keys = ["CAL BUS. & PROF. CODE § 16600", "CAL CIV. CODE § 1798.100"]
    missing_statutes = [key for key in needed_statute_keys if not (corpus.get(key, {}).get("text") or "").strip()]
    result: dict[str, Any] = {
        "run_mode": "live" if settings.gemini_api_key else "offline",
        "demo_file": "demo/sample_msa.txt",
        "matching_rule": "A planted risk matches a reported risk only when at least one referenced clause contains an expected section number and an exact quote contains the planted quote anchor (whitespace/case/smart-quote normalization only). Cross-clause recall additionally requires at least two distinct referenced clause IDs.",
        "risk_recall": _status("not run: GEMINI_API_KEY missing" if not settings.gemini_api_key else "not run", metric="matched planted risks / total planted risks"),
        "cross_clause_recall": _status("not run: GEMINI_API_KEY missing" if not settings.gemini_api_key else "not run", metric="matched planted cross-clause risks / total planted cross-clause risks"),
        "quote_grounding_rate": _status("not run: GEMINI_API_KEY missing" if not settings.gemini_api_key else "not run", metric="reported risk quotes present in source / reported risk quotes"),
        "citation_precision": _status(BLOCKED if missing_statutes else "not run: live analysis not run", metric="eligible cited authorities resolving to authority-bank entries / eligible cited authorities"),
        "claim_verification_rate": _status(BLOCKED if missing_statutes else "not run: GEMINI_API_KEY missing" if not settings.gemini_api_key else "not run: live analysis not run", metric="verified claims / claims"),
        "required_statute_text": {key: ("BLOCKED: statute text not loaded" if key in missing_statutes else "loaded") for key in needed_statute_keys},
        "cal_bpc_16600_support_check": _status(BLOCKED if "CAL BUS. & PROF. CODE § 16600" in missing_statutes else "not run: live analysis not run", metric="independent support check against loaded statute text"),
        "cal_civ_1798_100_support_check": _status(BLOCKED if "CAL CIV. CODE § 1798.100" in missing_statutes else "not run: live analysis not run", metric="independent support check against loaded statute text"),
        "fabrication_test": await _fabrication_check(),
    }

    if settings.gemini_api_key:
        try:
            from app.agents.workflow import LegalWorkflow
            parsed = ingest_document(source.encode("utf-8"), "text/plain", DEMO.name)
            workflow = LegalWorkflow()
            try:
                output = await workflow.run({
                    "filename": DEMO.name,
                    "mime_type": "text/plain",
                    "document_bytes": source.encode("utf-8"),
                    "parsed_document": parsed.model_dump(),
                    "document_text": parsed.text,
                    "page_texts": parsed.page_texts,
                    "progress": [],
                    "warnings": [],
                })
                live = _status_from_memo(output.get("memo", {}), expected, source)
                for name in ("risk_recall", "cross_clause_recall", "quote_grounding_rate"):
                    result[name] = live[name]
                if not missing_statutes:
                    result["citation_precision"] = live["citation_precision"]
                    result["claim_verification_rate"] = live["claim_verification_rate"]
            finally:
                close = getattr(workflow.resolver, "close", None)
                if close:
                    await close()
        except Exception as exc:
            reason = f"not run: live pipeline unavailable ({type(exc).__name__})"
            for name in ("risk_recall", "cross_clause_recall", "quote_grounding_rate", "claim_verification_rate"):
                result[name] = _status(BLOCKED if name == "claim_verification_rate" and missing_statutes else reason, metric=result[name]["metric"])
            result["live_pipeline_error"] = type(exc).__name__

    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _display(result: dict[str, Any]) -> None:
    labels = [
        ("Risk recall", "risk_recall"), ("Cross-clause recall", "cross_clause_recall"),
        ("Quote grounding rate", "quote_grounding_rate"), ("Citation precision", "citation_precision"),
        ("Claim verification rate", "claim_verification_rate"), ("Fabrication test", "fabrication_test"),
    ]
    print("\nLegal Copilot evaluation")
    print("| Metric | Result |")
    print("|---|---|")
    for label, key in labels:
        entry = result[key]
        if key == "fabrication_test":
            display = f"{entry['status']} ({entry['result_status']})"
        elif entry.get("value") is not None:
            display = f"{entry['value']:.1%} ({entry.get('matched', entry.get('grounded', entry.get('verified', entry.get('resolved_bank_authorities', 0))))}/{entry.get('total', entry.get('total_cited_authorities', 0))})"
        else:
            display = entry["status"]
        print(f"| {label} | {display} |")
    print(f"\nWrote {OUTPUT}")


def main() -> int:
    if settings.gemini_api_key:
        result = asyncio.run(evaluate())
    else:
        # Offline verification is fully in-memory; avoid creating an event loop/network socket.
        pending = evaluate()
        try:
            pending.send(None)
        except StopIteration as completed:
            result = completed.value
        else:
            pending.close()
            raise RuntimeError("Offline evaluation unexpectedly attempted asynchronous I/O.")
    _display(result)
    return 0 if result["fabrication_test"]["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
