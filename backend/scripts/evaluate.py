"""Evaluate the real Legal Copilot pipeline when configured; otherwise run safe offline checks.

Usage from repo root: ``python backend/scripts/evaluate.py``.
Uploaded/demo content is read only for this explicit evaluation command. Results contain
metrics and blocked reasons, not document text.

Risk match rule: strict quote-anchor recall requires at least one reported clause section
to overlap an expected section AND an exact reported quote to overlap the planted quote
anchor (whitespace/case/smart-quote normalization only). Section-match recall ignores
the quote anchor and requires only section overlap. Cross-clause strict recall additionally
requires two or more distinct clause IDs.
"""
from __future__ import annotations

import asyncio
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.config import MIN_SUPPORT_QUOTE_CHARS, settings  # noqa: E402
from app.ingestion import ingest_document  # noqa: E402
from app.verification.bank import AuthorityBank  # noqa: E402
from app.verification.extract import extract_citations, span_in_text  # noqa: E402
from app.verification.models import Authority, Claim, Citation, SupportVerdict  # noqa: E402
from app.verification.resolvers import StaticCorpusResolver  # noqa: E402
from app.verification.verifier import verify_claim  # noqa: E402
from app.services.gemini import GeminiCallWrapper, build_gemini_client, gemini_error_details  # noqa: E402
from pydantic import BaseModel  # noqa: E402

DEMO = ROOT / "demo" / "sample_msa.txt"
EXPECTED = ROOT / "demo" / "expected_risks.json"
CORPUS = BACKEND / "data" / "statutes.json"
OUTPUT = BACKEND / "eval_results.json"
BLOCKED = "BLOCKED: statute text not loaded"
NOT_MEASURED = "not run: evaluator does not isolate per-statute support-check outcomes"
PROBE_KEYS = (
    "CAL BUS. & PROF. CODE § 16600",
    "CAL CIV. CODE § 1798.100",
    "EU REGULATION 2016/679 ART. 28",
)


def _status(value: str, *, metric: str) -> dict[str, Any]:
    return {"value": None, "status": value, "metric": metric}


class _PreflightReply(BaseModel):
    status: str


PREFLIGHT_TIMEOUT_SECONDS = 20


async def _bounded_preflight(name: str, operation) -> dict[str, Any]:
    """Run one preflight operation with a strict per-operation deadline and progress."""
    print(f"[preflight] started: {name} (timeout={PREFLIGHT_TIMEOUT_SECONDS}s)", flush=True)
    started = time.monotonic()
    try:
        value = await asyncio.wait_for(operation(), timeout=PREFLIGHT_TIMEOUT_SECONDS)
        result = {"name": name, "status": "available", "elapsed_seconds": round(time.monotonic() - started, 3), "details": value}
    except asyncio.TimeoutError:
        result = {"name": name, "status": "unavailable", "reason": f"timed out after {PREFLIGHT_TIMEOUT_SECONDS}s", "elapsed_seconds": round(time.monotonic() - started, 3)}
    except Exception as exc:
        message = str(exc)
        if settings.gemini_api_key:
            message = message.replace(settings.gemini_api_key, "[REDACTED]")
        result = {
            "name": name, "status": "unavailable", "reason": f"{type(exc).__name__}: {message[:500]}",
            "http_status": getattr(exc, "code", None) or getattr(exc, "status_code", None),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    print(f"[preflight] finished: {name}; status={result['status']}; elapsed={result['elapsed_seconds']}s", flush=True)
    return result


async def _preflight() -> dict[str, Any]:
    """Bound config, local input, ingestion, offline verification, Gemini, and CourtListener checks."""
    results: list[dict[str, Any]] = []
    print("[preflight] config loaded; key configured=" + str(bool(settings.gemini_api_key)) + "; primary=" + settings.gemini_model, flush=True)
    results.append({"name": "config", "status": "available", "details": {"gemini_key_configured": bool(settings.gemini_api_key), "primary_model": settings.gemini_model, "support_model": settings.support_check_model, "fallback_model": settings.gemini_fallback_model or None}})

    async def load_inputs():
        return await asyncio.to_thread(lambda: {
            "document_bytes": DEMO.read_bytes(),
            "expected_bytes": EXPECTED.read_bytes(),
            "corpus_bytes": CORPUS.read_bytes(),
        })
    input_check = await _bounded_preflight("local_input_read", load_inputs)
    results.append(input_check)
    if input_check["status"] != "available":
        return {"checks": results, "case_lookup": {"status": "unavailable", "reason": "preflight input read failed"}}
    raw = input_check["details"]["document_bytes"]

    async def ingest_check():
        parsed = await asyncio.to_thread(ingest_document, raw, "text/plain", DEMO.name)
        return {"characters": len(parsed.text), "clauses": len(parsed.clauses)}
    results.append(await _bounded_preflight("document_ingestion", ingest_check))

    results.append(await _bounded_preflight("local_citation_verification", _fabrication_check))

    async def gemini_check():
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        client = build_gemini_client(settings.gemini_api_key)
        try:
            wrapper = GeminiCallWrapper(client, fallback_model=settings.gemini_fallback_model)
            response, actual_model = await wrapper.generate(
                'Return a JSON object with status set to "ok".', _PreflightReply, settings.gemini_model
            )
            return {"status": response.status, "requested_model": settings.gemini_model, "actual_model": actual_model, "fallback_used": actual_model != settings.gemini_model}
        finally:
            close = getattr(client.aio, "aclose", None)
            if close:
                await close()
    results.append(await _bounded_preflight("gemini_json_probe", gemini_check))

    async def courtlistener_check():
        from app.verification.resolvers import CourtListenerResolver
        resolver = CourtListenerResolver()
        try:
            headers = {"Authorization": f"Token {resolver.token}"} if resolver.token else {}
            response = await resolver._send("get", f"{resolver.API}/search/", params={"q": "contract", "type": "o", "page_size": 1}, headers=headers)
            response.raise_for_status()
            return {"http_status": response.status_code, "case_lookup_available": True}
        finally:
            await resolver.close()
    courtlistener = await _bounded_preflight("courtlistener_case_lookup", courtlistener_check)
    results.append(courtlistener)
    case_lookup = {"status": "available" if courtlistener["status"] == "available" else "unavailable"}
    if case_lookup["status"] == "unavailable":
        case_lookup["reason"] = courtlistener.get("reason", "CourtListener preflight failed")
    print(f"[preflight] case lookup={case_lookup['status']}; full workflow may continue with static corpus", flush=True)
    return {"checks": results, "case_lookup": case_lookup}


def _reported_sections(risk: dict, clauses: dict[str, dict]) -> set[str]:
    sections: set[str] = set()
    for clause_id in risk.get("clause_ids", []):
        clause = clauses.get(clause_id)
        if not clause:
            continue
        heading = clause.get("heading") or ""
        for match in re.finditer(r"(?<!\d)(\d+(?:\.\d+)+)\b", heading + "\n" + clause.get("text", "")[:160]):
            sections.add(match.group(1))
    return sections


def _risk_diagnostics(memo: dict, expected: dict, source: str) -> tuple[set[str], set[str], set[str], list[dict[str, Any]]]:
    clauses = {clause["id"]: clause for clause in memo.get("clauses", [])}
    risks = memo.get("risks", [])
    matched: set[str] = set()
    section_matched: set[str] = set()
    cross_matched: set[str] = set()
    reported = [{"risk": risk, "sections": _reported_sections(risk, clauses)} for risk in risks]
    diagnostics: list[dict[str, Any]] = []
    for planted in expected["planted_risks"]:
        expected_sections = set(planted["sections"])
        candidates = []
        for item in reported:
            risk = item["risk"]
            overlap = sorted(expected_sections.intersection(item["sections"]))
            quote_overlap = any(span_in_text(planted["quote"], quote) for quote in risk.get("exact_quotes", []))
            cross_clause_supported = len(set(risk.get("clause_ids", []))) >= 2
            if overlap:
                section_matched.add(planted["id"])
            matched_by_rule = bool(overlap and quote_overlap)
            if matched_by_rule:
                matched.add(planted["id"])
                if planted.get("cross_clause") and cross_clause_supported:
                    cross_matched.add(planted["id"])
            # Diagnostic ranking intentionally does not change the exact match rule.
            rank = (int(matched_by_rule), len(overlap), int(quote_overlap), int(cross_clause_supported))
            candidates.append((rank, {
                "risk_id": risk.get("risk_id"),
                "title": risk.get("title"),
                "reported_sections": sorted(item["sections"]),
                "overlapping_sections": overlap,
                "quote_anchor_overlap": quote_overlap,
                "reported_quote_spans": risk.get("exact_quotes", []),
                "cross_clause_ids": risk.get("clause_ids", []),
            }))
        candidates.sort(key=lambda row: row[0], reverse=True)
        closest = candidates[0][1] if candidates else None
        diagnostics.append({
            "planted_risk_id": planted["id"],
            "title": planted.get("title", planted["id"]),
            "expected_sections": sorted(expected_sections),
            "expected_quote_anchor": planted["quote"],
            "expected_quote_found_verbatim_in_document": planted["quote"] in source,
            "matched": planted["id"] in matched,
            "section_matched": planted["id"] in section_matched,
            "cross_clause_expected": bool(planted.get("cross_clause")),
            "cross_clause_matched": planted["id"] in cross_matched,
            "closest_reported_risk": closest,
        })
    return matched, cross_matched, section_matched, diagnostics


def _per_claim_outcomes(memo: dict) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    authorities = {item.get("id"): item for item in memo.get("authority_bank", [])}
    claims = []
    authority_rows: list[dict[str, Any]] = []
    for claim in memo.get("claims", []):
        result = claim.get("result") or {}
        claim_status = result.get("status", "unverified")
        reasons = result.get("reasons", [])
        quotes = result.get("authority_quotes", [])
        loaded_authority_ids = [
            authority_id for authority_id in claim.get("authority_ids", [])
            if (authorities.get(authority_id) or {}).get("text")
        ]
        missing_text_ids = [authority_id for authority_id in claim.get("authority_ids", []) if authority_id not in loaded_authority_ids]
        claim_row = {
            "claim_id": claim.get("claim_id"),
            "claim": claim.get("text", ""),
            "status": claim_status,
            "authority_ids": claim.get("authority_ids", []),
            "support_quotes": quotes,
            "reason": " ".join(reasons) if claim_status in {"unverified", "existence_only"} else None,
            "authority_text_loaded_count": len(loaded_authority_ids),
            "authority_text_unavailable_count": len(missing_text_ids),
            "support_checker_call_possible": bool(loaded_authority_ids),
            "support_checker_called": False,
            "support_checker_skip_reason": "All cited authorities are existence-only with no text; verifier skips the checker." if not loaded_authority_ids else None,
            "cited_authorities": [],
        }
        claims.append(claim_row)
        ids = claim.get("authority_ids", [])
        for authority_id in ids:
            authority = authorities.get(authority_id)
            if not authority:
                authority_rows.append({
                    "claim_id": claim.get("claim_id"), "authority_id": authority_id,
                    "authority": None, "normalized_key": None, "resolver_found_entry": False,
                    "authority_text_loaded": False, "support_checker_called": False,
                    "status": "rejected", "support_quote": None,
                    "reason": f"Authority ID [{authority_id}] is absent from the returned authority bank.",
                })
                continue
            quote_is_attributable = len(ids) == 1
            if not authority.get("text"):
                authority_reason = "Checker not called: this authority has no loaded source text (existence-only)."
            elif not quote_is_attributable:
                authority_reason = "Verifier result is claim-level; it does not map a support quote to one authority among multiple IDs."
            elif claim_status in {"unverified", "existence_only"}:
                authority_reason = " ".join(reasons)
            else:
                authority_reason = None
            row = {
                "claim_id": claim.get("claim_id"), "authority_id": authority_id,
                "authority": authority.get("key"), "normalized_key": authority.get("key"),
                "resolver_found_entry": True, "title": authority.get("title"),
                "source_status": authority.get("status"),
                "authority_text_loaded": bool(authority.get("text")),
                "support_checker_called": bool(authority.get("text")),
                "status": claim_status,
                "support_quote": (quotes[0] if len(quotes) == 1 else None) if quote_is_attributable else None,
                "reason": authority_reason,
            }
            claim_row["cited_authorities"].append(row)
            authority_rows.append(row)
    return claims, authority_rows


def _document_expectation_checks(expected: dict, source: str) -> list[dict[str, Any]]:
    rows = []
    for planted in expected["planted_risks"]:
        section_results = {
            section: bool(re.search(rf"(?m)^\s*{re.escape(section)}(?:\s|\.)", source))
            for section in planted["sections"]
        }
        rows.append({
            "planted_risk_id": planted["id"],
            "sections_found": section_results,
            "all_sections_found": all(section_results.values()),
            "expected_quote_found_verbatim": planted["quote"] in source,
        })
    return rows


def _status_from_memo(memo: dict, expected: dict, source: str) -> dict[str, Any]:
    risks = memo.get("risks", [])
    matched, cross_matched, section_matched, diagnostics = _risk_diagnostics(memo, expected, source)
    claims, per_authority = _per_claim_outcomes(memo)
    all_quotes = [quote for risk in risks for quote in risk.get("exact_quotes", [])]
    grounded_quotes = sum(1 for quote in all_quotes if span_in_text(quote, source))

    authorities = {item.get("id"): item for item in memo.get("authority_bank", [])}
    cited_ids: set[str] = set()
    for claim in memo.get("claims", []):
        cited_ids.update(claim.get("authority_ids", []))
    resolved_count = len(cited_ids.intersection(authorities))
    distinct_authority_precision = resolved_count / len(cited_ids) if cited_ids else None
    memo_claims = memo.get("claims", [])
    claim_verification = sum(1 for claim in memo_claims if (claim.get("result") or {}).get("status") == "verified") / len(memo_claims) if memo_claims else None
    cross_total = sum(1 for risk in expected["planted_risks"] if risk.get("cross_clause"))
    return {
        "risk_recall": {"value": len(matched) / len(expected["planted_risks"]) if expected["planted_risks"] else None, "matched": len(matched), "total": len(expected["planted_risks"]), "status": "completed"},
        "section_match_recall": {"value": len(section_matched) / len(expected["planted_risks"]) if expected["planted_risks"] else None, "matched": len(section_matched), "total": len(expected["planted_risks"]), "status": "completed"},
        "cross_clause_recall": {"value": len(cross_matched) / cross_total if cross_total else None, "matched": len(cross_matched), "total": cross_total, "status": "completed"},
        "quote_grounding_rate": {"value": grounded_quotes / len(all_quotes) if all_quotes else None, "grounded": grounded_quotes, "total": len(all_quotes), "status": "completed"},
        "distinct_authority_precision": {"value": distinct_authority_precision, "distinct_authorities_found_in_bank": resolved_count, "distinct_authorities_cited": len(cited_ids), "counting_rule": "Unique cited authority IDs across all memo claims; numerator counts IDs present in the returned authority bank, denominator counts all distinct IDs cited.", "status": "completed" if cited_ids else "not run: no cited authorities"},
        "claim_verification_rate": {"value": claim_verification, "verified": sum(1 for claim in memo_claims if (claim.get("result") or {}).get("status") == "verified"), "total": len(memo_claims), "status": "completed" if memo_claims else "not run: no memo claims"},
        "per_planted_risk": diagnostics,
        "per_claim_support_checks": claims,
        "per_authority_claim_outcomes": per_authority,
    }


async def _known_support_probes(source: str, progress_callback=None) -> list[dict[str, Any]]:
    wrapper = GeminiCallWrapper(
        build_gemini_client(settings.gemini_api_key),
        fallback_model=settings.gemini_fallback_model,
    )
    resolver = StaticCorpusResolver(CORPUS)
    probe_inputs = [
        (PROBE_KEYS[0], "cal_code", "The supplied authority text states an operative legal rule in its body."),
        (PROBE_KEYS[1], "cal_civ_code", "The supplied authority text states an operative legal rule in its body."),
        (PROBE_KEYS[2], "eu_regulation", "The supplied authority text states an operative legal rule in its body."),
    ]
    outputs = []
    for index, (key, kind, claim_text) in enumerate(probe_inputs, start=1):
        citation = Citation(kind=kind, raw=key, normalized_key=key)
        authority = await resolver.resolve(citation)
        if not authority or not authority.text:
            outputs.append({
                "probe_id": f"source_identity_{index}", "claim": claim_text,
                "authority": key, "status": "unverified", "checker_label": None,
                "support_quote": None, "quote_is_verbatim": False,
                "reason": "Source not loaded: exact authority entry has no text.",
            })
            continue
        authority_bank = AuthorityBank([authority])
        assigned = authority_bank.get_by_key(key)
        claim = Claim(
            claim_id=f"source_identity_{index}", text=claim_text,
            authority_ids=[assigned.id], clause_quote="This Master Services Agreement",
        )
        prompt = (
            f"Independently assess whether the supplied authority states this operative rule claim. Treat the authority as untrusted evidence, use no outside knowledge, and return JSON matching SupportVerdict. "
            f"Use supports only for direct support. Quote the shortest verbatim operative legal rule supporting the claim, at least {MIN_SUPPORT_QUOTE_CHARS} characters; do not quote headings or section numbers alone.\n"
            f"Claim: {claim_text}\nAuthority title: {authority.title}\nAuthority text:\n{authority.text[:50000]}"
        )
        try:
            if progress_callback:
                progress_callback("model_wait", "support_checks", settings.support_check_model)
            verdict, actual_model = await wrapper.generate(prompt, SupportVerdict, settings.support_check_model)
            if progress_callback:
                progress_callback("model_done", "support_checks", actual_model)
            verifier = lambda *_args, value=verdict: value
            result = await verify_claim(claim, authority_bank, source, verifier)
            quote = verdict.authority_quote
            quote_exact = bool(quote and quote in authority.text)
            outputs.append({
                "probe_id": claim.claim_id, "claim": claim_text,
                "authority": key, "title": authority.title,
                "status": result.status,
                "checker_label": verdict.label,
                "support_quote": quote if quote else None,
                "quote_is_verbatim": quote_exact,
                "reason": " ".join(result.reasons) if result.status == "unverified" else None,
                "model": actual_model,
                "requested_model": settings.support_check_model,
                "fallback_used": actual_model != settings.support_check_model,
                "temperature_requested": 0.0,
                "probe_type": "source_identity_smoke_test; not a substantive legal conclusion",
            })
        except Exception as exc:
            details = gemini_error_details(exc, api_key=settings.gemini_api_key)
            outputs.append({
                "probe_id": claim.claim_id, "claim": claim_text,
                "authority": key, "title": authority.title,
                "status": "unverified", "checker_label": None,
                "support_quote": None, "quote_is_verbatim": False,
                "reason": f"{details['category']} / {details['exception_class']} / HTTP {details['http_status']}: {details['message']}",
                "error": details,
            })
    return outputs


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


async def evaluate(output_path: Path = OUTPUT, progress_callback=None) -> dict[str, Any]:
    preflight = await _preflight()
    source = DEMO.read_text(encoding="utf-8")
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    corpus = json.loads(CORPUS.read_text(encoding="utf-8")) if CORPUS.exists() else {}
    needed_statute_keys = ["CAL BUS. & PROF. CODE § 16600", "CAL CIV. CODE § 1798.100"]
    missing_statutes = [key for key in needed_statute_keys if not (corpus.get(key, {}).get("text") or "").strip()]
    gdpr_article_33_loaded = bool(
        (corpus.get("EU REGULATION 2016/679 ART. 33", {}).get("text") or "").strip()
    )
    if not gdpr_article_33_loaded:
        missing_statutes.append("EU REGULATION 2016/679 Article 33")
    result: dict[str, Any] = {
        "run_mode": "live" if settings.gemini_api_key else "offline",
        "model_metadata": {
            "configured_primary": settings.gemini_model,
            "configured_support_checker": settings.support_check_model,
            "configured_fallback": settings.gemini_fallback_model or None,
            "temperature_requested": 0.0,
            "model_calls": [],
            "known_probe_model_calls": [],
        },
        "preflight": preflight,
        "case_lookup": preflight["case_lookup"],
        "demo_file": "demo/sample_msa.txt",
        "matching_rule": "Strict quote-anchor recall: expected section overlap AND exact quote-anchor overlap (whitespace/case/smart-quote normalization only). Section-match recall: expected section overlap regardless of quote. Cross-clause strict recall: strict quote-anchor match plus at least two distinct referenced clause IDs.",
        "expected_risk_document_checks": _document_expectation_checks(expected, source),
        "risk_recall": _status("not run: GEMINI_API_KEY missing" if not settings.gemini_api_key else "not run", metric="matched planted risks / total planted risks"),
        "section_match_recall": _status("not run: GEMINI_API_KEY missing" if not settings.gemini_api_key else "not run", metric="planted risks with any expected section overlap / total planted risks"),
        "cross_clause_recall": _status("not run: GEMINI_API_KEY missing" if not settings.gemini_api_key else "not run", metric="matched planted cross-clause risks / total planted cross-clause risks"),
        "quote_grounding_rate": _status("not run: GEMINI_API_KEY missing" if not settings.gemini_api_key else "not run", metric="reported risk quotes present in source / reported risk quotes"),
        "distinct_authority_precision": _status("not run: live analysis not run", metric="distinct cited authority IDs found in bank / distinct cited authority IDs"),
        "claim_verification_rate": _status(BLOCKED if missing_statutes else "not run: GEMINI_API_KEY missing" if not settings.gemini_api_key else "not run: live analysis not run", metric="verified claims / claims"),
        "required_statute_text": {key: ("BLOCKED: statute text not loaded" if key in missing_statutes else "loaded") for key in [*needed_statute_keys, "EU REGULATION 2016/679 Article 33"]},
        "set_statute_text_script_exists": (BACKEND / "scripts" / "set_statute_text.py").exists(),
        "cal_bpc_16600_support_check": _status(BLOCKED if "CAL BUS. & PROF. CODE § 16600" in missing_statutes else NOT_MEASURED, metric="independent support check against loaded statute text"),
        "cal_civ_1798_100_support_check": _status(BLOCKED if "CAL CIV. CODE § 1798.100" in missing_statutes else NOT_MEASURED, metric="independent support check against loaded statute text"),
        "gdpr_article_33_support_check": _status(BLOCKED if "EU REGULATION 2016/679 Article 33" in missing_statutes else NOT_MEASURED, metric="independent support check against loaded GDPR Article 33 text"),
        "fabrication_test": await _fabrication_check(),
        "per_claim_support_checks": [],
        "per_statute_support_checks": [],
        "known_support_probes": [],
    }

    if settings.gemini_api_key:
        try:
            from app.agents.workflow import LegalWorkflow
            from app.verification.resolvers import CompositeResolver, CourtListenerResolver, StaticCorpusResolver
            parsed = ingest_document(source.encode("utf-8"), "text/plain", DEMO.name)
            resolvers = [StaticCorpusResolver()]
            if preflight["case_lookup"]["status"] == "available":
                resolvers.append(CourtListenerResolver())
            workflow = LegalWorkflow(resolver=CompositeResolver(resolvers), progress_callback=progress_callback)
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
                result["model_metadata"]["model_calls"] = output.get("memo", {}).get("analysis_metadata", {}).get("model_calls", [])
                for name in ("risk_recall", "section_match_recall", "cross_clause_recall", "quote_grounding_rate", "distinct_authority_precision"):
                    result[name] = live[name]
                result["per_planted_risk"] = live["per_planted_risk"]
                result["per_claim_support_checks"] = live["per_claim_support_checks"]
                result["per_statute_support_checks"].extend(live["per_authority_claim_outcomes"])
                if not missing_statutes:
                    result["claim_verification_rate"] = live["claim_verification_rate"]
            finally:
                close = getattr(workflow.resolver, "close", None)
                if close:
                    await close()
        except Exception as exc:
            error_details = gemini_error_details(exc, api_key=settings.gemini_api_key)
            reason = f"not run: live pipeline unavailable ({error_details['category']}; {error_details['exception_class']}; HTTP {error_details['http_status']}; {error_details['message']})"
            for name in ("risk_recall", "section_match_recall", "cross_clause_recall", "quote_grounding_rate", "claim_verification_rate"):
                result[name] = _status(BLOCKED if name == "claim_verification_rate" and missing_statutes else reason, metric=result[name]["metric"])
            result["live_pipeline_error"] = error_details

        try:
            if progress_callback:
                progress_callback("stage_started", "support_checks", None)
            probes = await _known_support_probes(source, progress_callback)
            result["known_support_probes"] = probes
            result["model_metadata"]["known_probe_model_calls"] = [
                {"authority": item["authority"], "requested_model": item.get("requested_model", settings.support_check_model), "model": item.get("model"), "fallback_used": item.get("fallback_used", False), "status": item["status"], "temperature_requested": item.get("temperature_requested", 0.0)}
                for item in probes
            ]
            result["per_statute_support_checks"].extend(probes)
            check_field_by_key = {
                PROBE_KEYS[0]: "cal_bpc_16600_support_check",
                PROBE_KEYS[1]: "cal_civ_1798_100_support_check",
                PROBE_KEYS[2]: "gdpr_article_28_support_check",
            }
            for item in probes:
                field = check_field_by_key.get(item["authority"])
                if field:
                    result[field] = {
                        "value": None,
                        "status": f"source-identity smoke test: {item['status']}",
                        "metric": "not a substantive legal conclusion",
                        "support_quote": item.get("support_quote"),
                        "reason": item.get("reason"),
                    }
        except Exception as exc:
            result["known_support_probe_error"] = gemini_error_details(exc, api_key=settings.gemini_api_key)

    all_calls = result["model_metadata"].get("model_calls", []) + result["model_metadata"].get("known_probe_model_calls", [])
    result["model_metadata"]["fallback_used"] = any(bool(call.get("fallback_used")) for call in all_calls)

    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _display(result: dict[str, Any], output_path: Path = OUTPUT) -> None:
    labels = [
        ("Section-match recall", "section_match_recall"), ("Strict quote-anchor recall", "risk_recall"),
        ("Cross-clause recall", "cross_clause_recall"), ("Quote grounding rate", "quote_grounding_rate"),
        ("Distinct authority precision", "distinct_authority_precision"),
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
            numerator = next((entry[key] for key in ("matched", "grounded", "verified", "distinct_authorities_found_in_bank") if key in entry), 0)
            denominator = next((entry[key] for key in ("total", "distinct_authorities_cited") if key in entry), 0)
            display = f"{entry['value']:.1%} ({numerator}/{denominator})"
        else:
            display = entry["status"]
        print(f"| {label} | {display} |")
    print("\nRisk matching rule:", result["matching_rule"])
    print("\nExpected contract evidence checks:")
    for item in result.get("expected_risk_document_checks", []):
        print(f"- {item['planted_risk_id']}: sections={item['sections_found']}; quote_anchor_verbatim={item['expected_quote_found_verbatim']}")
    if result.get("per_planted_risk"):
        print("\nPer-planted-risk matching diagnostics:")
        for item in result["per_planted_risk"]:
            closest = item.get("closest_reported_risk")
            print(f"- {item['planted_risk_id']}: expected sections={item['expected_sections']}; quote={item['expected_quote_anchor']!r}; matched={item['matched']}; cross-clause matched={item['cross_clause_matched']}")
            print(f"  closest reported risk: {closest if closest else 'none'}")
    if result.get("known_support_probes"):
        print("\nLive source-identity support probes (not legal conclusions):")
        for item in result["known_support_probes"]:
            print(f"- {item['authority']}: status={item['status']}; checker_label={item.get('checker_label')}; quote_verbatim={item.get('quote_is_verbatim')}; quote={item.get('support_quote')!r}; reason={item.get('reason')}")
    if result.get("live_pipeline_error"):
        error = result["live_pipeline_error"]
        status = f"HTTP {error['http_status']}" if error.get("http_status") is not None else "HTTP status unavailable"
        print(
            "\nGemini unavailable: "
            f"{error['category']} · {error['exception_class']} · {status} · {error['message']}"
        )
    print(f"\nWrote {output_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--preflight-only", action="store_true", help="run only bounded config/provider/input diagnostics; do not analyze the demo")
    args = parser.parse_args()
    if args.preflight_only:
        print("[preflight] entering bounded runner", flush=True)
        result = asyncio.run(asyncio.wait_for(_preflight(), timeout=6 * PREFLIGHT_TIMEOUT_SECONDS))
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0
    if settings.gemini_api_key:
        progress_state = {"stage": "setup", "waiting_on_model": False, "model": None}

        def progress(event: str, stage: str, model: str | None):
            progress_state["stage"] = stage
            trace_line = None
            if event == "stage_started":
                progress_state["waiting_on_model"] = False
                trace_line = f"[stage] started: {stage}"
            elif event == "model_wait":
                progress_state["waiting_on_model"] = True
                progress_state["model"] = model
                trace_line = f"[model] waiting: stage={stage}; model={model}"
            elif event == "model_done":
                progress_state["waiting_on_model"] = False
                trace_line = f"[model] returned: stage={stage}; model={model}"
            elif event == "model_failed":
                progress_state["waiting_on_model"] = False
                trace_line = f"[model] failed: stage={stage}; model={model}"
            if trace_line:
                print(trace_line, flush=True)
                trace_path = os.environ.get("LEGAL_EVAL_PROGRESS_FILE")
                if trace_path:
                    with open(trace_path, "a", encoding="utf-8") as trace:
                        trace.write(trace_line + "\n")

        try:
            print("[evaluation] started; overall timeout=480s", flush=True)
            result = asyncio.run(asyncio.wait_for(evaluate(args.output, progress_callback=progress), timeout=480))
            print("[stage] evaluation completed", flush=True)
        except asyncio.TimeoutError:
            waiting = f"; waiting on model {progress_state['model']}" if progress_state["waiting_on_model"] else ""
            reason = f"not run: overall 8-minute timeout during {progress_state['stage']}{waiting}"
            result = {
                "run_mode": "live",
                "timed_out_stage": progress_state["stage"],
                "timed_out_waiting_on_model": progress_state["waiting_on_model"],
                "model_metadata": {
                    "configured_primary": settings.gemini_model,
                    "configured_support_checker": settings.support_check_model,
                    "configured_fallback": settings.gemini_fallback_model or None,
                    "temperature_requested": 0.0,
                    "model_calls": [],
                    "fallback_used": False,
                },
                "matching_rule": "Strict quote-anchor recall requires expected section overlap and quote-anchor overlap; section-match recall requires section overlap only; cross-clause strict recall also requires two distinct clause IDs.",
                **{name: _status(reason, metric=name) for name in ("risk_recall", "section_match_recall", "cross_clause_recall", "quote_grounding_rate", "distinct_authority_precision", "claim_verification_rate")},
                "fabrication_test": {"status": "not run: overall timeout", "result_status": "not run"},
            }
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"[timeout] {reason}", flush=True)
            trace_path = os.environ.get("LEGAL_EVAL_PROGRESS_FILE")
            if trace_path:
                with open(trace_path, "a", encoding="utf-8") as trace:
                    trace.write(f"[timeout] {reason}\n")
    else:
        # Offline verification is fully in-memory; avoid creating an event loop/network socket.
        pending = evaluate(args.output)
        try:
            pending.send(None)
        except StopIteration as completed:
            result = completed.value
        else:
            pending.close()
            raise RuntimeError("Offline evaluation unexpectedly attempted asynchronous I/O.")
    _display(result, args.output)
    return 0 if result["fabrication_test"]["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
