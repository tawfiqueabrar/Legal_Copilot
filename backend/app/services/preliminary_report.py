"""Deterministic, quote-gated assembly of the preliminary assessment report."""
from __future__ import annotations

import re
from typing import Any

from app.agents.risk_models import (
    EvidenceGap,
    LegalSource,
    MemoRisk,
    NotAssessedItem,
    RiskLegalReference,
)
from app.verification.extract import extract_citations


ASSESSMENT_LINE = "Potential risks found; no legal violation established"
REPORT_FOOTER = "This report does not establish an actual violation or provide a final legal opinion."
NOT_LOADED_NOTE = "The source library lacks loaded text for this jurisdiction or regime; it was not assessed."
_STATUS_LABELS = {
    "verified": "Verified",
    "existence_only": "Existence-only",
    "unverified": "Unverified",
    "rejected": "Rejected",
}
_GAP_PATTERN = re.compile(
    r"\[\s*(?:redacted|missing|omitted|truncated|cut\s+off)(?:[^\]]*)\]|\bredacted\b|"
    r"\b(?:text|pages?|sections?|attachments?)\s+(?:are\s+)?(?:missing|omitted|truncated)\b|"
    r"\b(?:missing|omitted|truncated)\s+(?:pages?|sections?|attachments?|portions?|parts?|text|content)\b|"
    r"\b(?:cut off|incomplete scan)\b",
    re.I,
)
_UNSAFE_CONCLUSION = re.compile(
    r"\b(?:violat(?:e|es|ed|ion)|illegal|unlawful|non[- ]?compliant|noncompliance|"
    r"breach(?:es|ed)?|unenforceable|enforceable|complies|compliant|required by law)\b",
    re.I,
)
_FREEFORM_AUTHORITY = re.compile(
    r"\b(?:HIPAA|GDPR|CCPA|CPRA|FERPA|GLBA)\b|\b(?:U\.\s*S\.\s*C\.|C\.\s*F\.\s*R\.)|\b(?:Article|Art\.?)\s+\d+",
    re.I,
)


def status_label(status: str) -> str:
    """Render the verifier's closed status vocabulary without model interpretation."""
    return _STATUS_LABELS[status]


def citation_check_line(status: str, applicability_note: str) -> str:
    return f"Citation check: {status_label(status)} — {applicability_note}"


def _as_dict(item: Any) -> dict:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return item if isinstance(item, dict) else {}


def _section(clause: dict) -> str:
    heading = str(clause.get("heading") or "").strip()
    match = re.match(r"^(\d+(?:\.\d+)*)(?:\.?\b|\s|$)", heading)
    return match.group(1) if match else heading or clause.get("id", "Unnumbered clause")


def _why_may_matter(risk: dict) -> str:
    explanation = str(risk.get("why_non_obvious") or "").strip()
    conditional = re.search(r"\b(?:may|could|if|depending|conditional)\b", explanation, re.I)
    if explanation and conditional and not _UNSAFE_CONCLUSION.search(explanation) and not extract_citations(explanation) and not _FREEFORM_AUTHORITY.search(explanation):
        return explanation
    return (
        "This wording may affect the parties’ contractual or operational risk allocation if the stated trigger occurs. "
        "Its practical effect could depend on the facts, contract context, and applicable jurisdiction."
    )


def _safe_title(risk: dict) -> str:
    title = str(risk.get("title") or "").strip()
    if _UNSAFE_CONCLUSION.search(title) or extract_citations(title) or _FREEFORM_AUTHORITY.search(title) or re.search(r"\b(?:verified|existence[- ]only|unverified|rejected)\b", title, re.I):
        return "Potential contract issue requiring review"
    return title or "Potential contract issue requiring review"


def _safe_action(risk: dict) -> str:
    action = str(risk.get("suggested_mitigation_clause") or "").strip()
    if _UNSAFE_CONCLUSION.search(action) or extract_citations(action) or _FREEFORM_AUTHORITY.search(action):
        return "Consider clarifying the contract wording and confirm the relevant facts and jurisdiction with qualified counsel."
    return action or "Review the contract wording with qualified counsel."


def _get_evidence(risk: dict, clauses: list[dict]) -> list[dict] | None:
    clause_by_id = {clause.get("id"): clause for clause in clauses}
    refs = []
    quoted_clause_ids = set()
    for quote in risk.get("exact_quotes", []):
        if not isinstance(quote, str) or not quote:
            return None
        matches = [clause_by_id[clause_id] for clause_id in risk.get("clause_ids", [])
                   if clause_id in clause_by_id and quote in str(clause_by_id[clause_id].get("text", ""))]
        if not matches:
            return None
        clause = matches[0]
        quoted_clause_ids.add(clause["id"])
        refs.append({"clause_id": clause["id"], "section": _section(clause), "quote": quote})
    if not refs or any(clause_id not in quoted_clause_ids for clause_id in risk.get("clause_ids", [])):
        return None
    return refs


def _article_mentions(text: str) -> set[int]:
    return {int(value) for value in re.findall(r"\b(?:Article|Art\.?)[ \t]*(\d{1,3})\b", text, re.I)}


def _mentions_gdpr(text: str) -> bool:
    return bool(re.search(r"\bGDPR\b|Regulation\s*\(\s*EU\s*\)\s*\d{4}\s*/\s*\d+", text, re.I))


def _authority_covers_article(authority: dict, article: int) -> bool:
    text = str(authority.get("text") or "")
    return bool(text.strip()) and bool(re.search(rf"\bArticle\s+{article}\b", text, re.I))


def _missing_article_risk(risk: dict, authority_by_id: dict[str, dict]) -> bool:
    queries = "\n".join(str(item) for item in risk.get("search_queries", []))
    if not _mentions_gdpr(queries):
        return False
    articles = _article_mentions(queries)
    if not articles:
        return False
    eu_authorities = [authority_by_id.get(item) for item in risk.get("authority_ids", [])]
    eu_authorities = [authority for authority in eu_authorities if authority and authority.get("kind") == "eu_regulation"]
    return any(not any(_authority_covers_article(authority, article) for authority in eu_authorities) for article in articles)


def _risk_status(statuses: list[str], *, source_not_loaded: bool) -> str:
    if source_not_loaded:
        return "unverified"
    # Conservative aggregation: any weaker backend status prevents a stronger report label.
    for status in ("rejected", "unverified", "existence_only", "verified"):
        if status in statuses:
            return status
    return "unverified"


def _regime_candidates(document_text: str, jurisdiction: dict) -> set[str]:
    candidates: set[str] = set()
    acronym_rules = {"HIPAA": r"\bHIPAA\b", "GDPR": r"\bGDPR\b", "UK GDPR": r"\bUK\s+GDPR\b", "CCPA": r"\bCCPA\b", "CPRA": r"\bCPRA\b", "FERPA": r"\bFERPA\b", "GLBA": r"\bGLBA\b"}
    for name, pattern in acronym_rules.items():
        if re.search(pattern, document_text, re.I):
            candidates.add(name)
    for name, pattern in (
        ("New York law", r"\bNew\s+York\b|\bNY\s+law\b"),
        ("California law", r"\bCalifornia\b|\bCal\.\s+(?:Bus|Civ)\.\b"),
        ("EU/EEA law", r"\b(?:EU|European Union|EEA|European Economic Area)\b"),
        ("UK law", r"\b(?:United Kingdom|England and Wales|UK law)\b"),
    ):
        if re.search(pattern, document_text, re.I):
            candidates.add(name)
    for article in _article_mentions(document_text):
        if re.search(r"\b(?:GDPR|Regulation\s*\(\s*EU\s*\))[^\n.]{0,100}\b(?:Article|Art\.?)\s*" + str(article) + r"\b|\b(?:Article|Art\.?)\s*" + str(article) + r"\b[^\n.]{0,100}\bGDPR\b", document_text, re.I):
            candidates.add(f"GDPR Article {article}")

    for match in re.finditer(r"\b(?:Article|Art\.?)\s*(\d{1,3})\b", document_text, re.I):
        context = document_text[max(0, match.start() - 100):match.end() + 100]
        if _mentions_gdpr(context):
            candidates.add(f"GDPR Article {int(match.group(1))}")

    for field in ("governing_law", "venue"):
        value = str(jurisdiction.get(field) or "")
        if value and value.casefold() not in {"unclear", "unknown"}:
            if re.search(r"\bNew\s+York\b", value, re.I):
                candidates.add("New York law")
            elif re.search(r"\bCalifornia\b", value, re.I):
                candidates.add("California law")
            elif re.search(r"\b(?:England|Wales|United Kingdom|UK)\b", value, re.I):
                candidates.add("UK law")
            elif re.search(r"\b(?:EU|European Union|EEA)\b", value, re.I):
                candidates.add("EU/EEA law")
            else:
                candidates.add(value.strip())
    for value in jurisdiction.get("data_subject_regions", []):
        value = str(value)
        if re.search(r"\b(?:EU|EEA|European Economic Area|European Union)\b", value, re.I):
            candidates.add("EU/EEA law")
    for value in jurisdiction.get("party_locations", []):
        value = str(value)
        if re.search(r"\bNew\s+York\b", value, re.I):
            candidates.add("New York law")
        if re.search(r"\bCalifornia\b", value, re.I):
            candidates.add("California law")
    return candidates


def _source_covers(name: str, authorities: list[dict]) -> bool:
    loaded = [item for item in authorities if str(item.get("text") or "").strip()]
    lowered = name.casefold()
    if lowered.startswith("gdpr article "):
        article = int(re.search(r"(\d+)$", name).group(1))
        return any(item.get("kind") == "eu_regulation" and _authority_covers_article(item, article) for item in loaded)
    if lowered == "gdpr" or lowered == "eu/eea law":
        return any(item.get("kind") in {"eu_regulation", "eu_directive"} for item in loaded)
    if lowered in {"ccpa", "cpra"}:
        return any(str(item.get("key", "")).startswith("CAL CIV. CODE") for item in loaded)
    if lowered == "uk gdpr":
        return any("uk gdpr" in (str(item.get("key", "")) + " " + str(item.get("title", ""))).casefold() for item in loaded)
    if lowered == "california law":
        return any(str(item.get("key", "")).startswith("CAL ") and "CAL " in str(item.get("key", "")) for item in loaded)
    if lowered == "new york law":
        return any("new york" in (str(item.get("key", "")) + str(item.get("title", ""))).casefold() for item in loaded)
    if lowered == "uk law":
        return any("united kingdom" in (str(item.get("key", "")) + str(item.get("title", ""))).casefold() for item in loaded)
    return any(lowered in (str(item.get("key", "")) + " " + str(item.get("title", ""))).casefold() for item in loaded)


def _evidence_gaps(document_text: str, clauses: list[dict], risks: list[dict]) -> list[EvidenceGap]:
    gaps: list[EvidenceGap] = []
    clauses_by_id = {item.get("id"): item for item in clauses}
    for match in _GAP_PATTERN.finditer(document_text):
        marker = match.group(0)
        clause_ids = [clause_id for clause_id, clause in clauses_by_id.items() if marker in str(clause.get("text", ""))]
        affected = [risk.get("risk_id", "") for risk in risks if set(risk.get("clause_ids", [])).intersection(clause_ids)]
        gaps.append(EvidenceGap(
            marker=marker,
            clause_ids=clause_ids,
            affected_risk_ids=affected,
            note="The marked or omitted material may affect findings that depend on it and cannot be fully assessed.",
        ))
    return gaps


def build_preliminary_report(
    *,
    document_name: str,
    document_text: str,
    clauses: list[dict],
    risks: list[dict],
    authority_bank: list[dict],
    claims: list[dict],
    draft_claims: list[dict],
    removed_claims: list[dict],
    jurisdiction: dict,
) -> dict:
    """Build report-only fields deterministically; all labels come from verifier results."""
    clauses = [_as_dict(item) for item in clauses]
    risks = [_as_dict(item) for item in risks]
    authority_bank = [_as_dict(item) for item in authority_bank]
    claims = [_as_dict(item) for item in claims]
    draft_claims = [_as_dict(item) for item in draft_claims]
    removed_claims = [_as_dict(item) for item in removed_claims]
    authority_by_id = {item.get("id"): item for item in authority_bank if item.get("id")}
    claims_by_id = {item.get("claim_id"): item for item in claims}
    draft_by_id = {item.get("claim_id"): item for item in draft_claims}
    removed_by_id = {item.get("claim_id"): item for item in removed_claims}

    legal_sources = [LegalSource(
        authority_id=item["id"], title=item.get("title", "Source"), source=item.get("source", ""),
        url=item.get("url", ""), retrieved_at=item.get("retrieved_at"),
    ) for item in authority_bank if str(item.get("text") or "").strip() and item.get("url")]

    candidates = _regime_candidates(document_text, jurisdiction)
    for risk in risks:
        query_text = "\n".join(str(value) for value in risk.get("search_queries", []))
        if _mentions_gdpr(query_text):
            candidates.update(f"GDPR Article {article}" for article in _article_mentions(query_text))
    not_assessed = [NotAssessedItem(name=name, note=NOT_LOADED_NOTE) for name in sorted(candidates) if not _source_covers(name, authority_bank)]

    report_risks: list[MemoRisk] = []
    report_raw_risks: list[dict] = []
    excluded_claim_ids: set[str] = set()
    for risk in risks:
        evidence = _get_evidence(risk, clauses)
        if evidence is None:
            continue
        quote_values = [entry["quote"] for entry in evidence]
        related_claims = []
        for claim_id, source_claim in draft_by_id.items():
            quote = str(source_claim.get("clause_quote") or "")
            quote_matches = any(quote and (quote in risk_quote or risk_quote in quote) for risk_quote in quote_values)
            ids_overlap = set(source_claim.get("authority_ids", [])).intersection(risk.get("authority_ids", []))
            if quote_matches and ids_overlap:
                related_claims.append((source_claim, claims_by_id.get(claim_id), removed_by_id.get(claim_id)))

        source_missing = False
        legal_references: list[RiskLegalReference] = []
        reference_statuses: list[str] = []
        missing_article = _missing_article_risk(risk, authority_by_id)
        source_missing = missing_article
        for authority_id in dict.fromkeys(risk.get("authority_ids", [])):
            authority = authority_by_id.get(authority_id)
            if not authority or not str(authority.get("text") or "").strip() or not authority.get("url"):
                source_missing = True
                continue
            if authority.get("kind") == "eu_regulation":
                article_mentions = _article_mentions("\n".join(str(value) for value in risk.get("search_queries", [])))
                if any(not _authority_covers_article(authority, article) for article in article_mentions):
                    source_missing = True
                    continue
            related_for_authority = []
            for source_claim, verified_claim, removed in related_claims:
                if authority_id not in source_claim.get("authority_ids", []):
                    continue
                record = verified_claim or {}
                result = record.get("result") if record else removed
                status = (result or {}).get("status")
                if status in _STATUS_LABELS:
                    related_for_authority.append((status, result or {}))
            ref_status = _risk_status([item[0] for item in related_for_authority], source_not_loaded=False)
            reference_statuses.extend(item[0] for item in related_for_authority)
            support_quotes = list(dict.fromkeys(
                quote
                for _, result in related_for_authority
                for quote in result.get("authority_quotes", [])
                if isinstance(quote, str) and quote and quote in str(authority.get("text") or "")
            ))
            legal_references.append(RiskLegalReference(authority_id=authority_id, status=ref_status, support_quotes=support_quotes))

        if not legal_references and (risk.get("authority_ids") or risk.get("search_queries")):
            source_missing = True
        if missing_article:
            legal_references = [reference for reference in legal_references if authority_by_id.get(reference.authority_id, {}).get("kind") != "eu_regulation"]
            for source_claim, _, _ in related_claims:
                if any(authority_by_id.get(authority_id, {}).get("kind") == "eu_regulation" for authority_id in source_claim.get("authority_ids", [])):
                    excluded_claim_ids.add(source_claim["claim_id"])
        citation_status = _risk_status(reference_statuses, source_not_loaded=source_missing)
        applicability_note = (
            "Source not loaded; applicability conditional; confirm the relevant facts and governing jurisdiction."
            if source_missing else
            "Applicability conditional; confirm the relevant facts and governing jurisdiction."
        )
        line = citation_check_line(citation_status, applicability_note)
        report_risk = MemoRisk.model_validate({
            **risk,
            "title": _safe_title(risk),
            "suggested_mitigation_clause": _safe_action(risk),
            "contract_evidence": evidence,
            "why_may_matter": _why_may_matter(risk),
            "legal_references": [item.model_dump() for item in legal_references],
            "citation_status": citation_status,
            "applicability_note": applicability_note,
            "citation_check_line": line,
            "source_not_loaded": source_missing,
        })
        report_risks.append(report_risk)
        report_raw_risks.append(risk)

    return {
        "title": "Preliminary Contract Risk Assessment",
        "document_name": document_name,
        "assessment_line": ASSESSMENT_LINE,
        "legal_sources_in_scope": legal_sources,
        "not_assessed": not_assessed,
        "risks": report_risks,
        "evidence_gaps": _evidence_gaps(document_text, clauses, report_raw_risks),
        "footer": REPORT_FOOTER,
        "excluded_claim_ids": sorted(excluded_claim_ids),
    }
