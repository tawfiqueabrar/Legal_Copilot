from collections.abc import Callable
import re
from app.config import MIN_SUPPORT_QUOTE_CHARS
from .bank import AuthorityBank
from .extract import extract_citations, span_in_text
from .models import Claim, ClaimResult, SupportVerdict


def _is_operative_support_quote(quote: str) -> bool:
    """Require a substantial, grounded sentence, while excluding heading-only snippets."""
    normalized = " ".join(quote.split())
    if len(normalized) < MIN_SUPPORT_QUOTE_CHARS:
        return False
    if not re.search(r"[.!?][\"')\]]*$", normalized):
        return False
    if re.fullmatch(r"(?i)(?:article|art\.?|section|sec\.?|§)\s*[\d.()\-a-z]+(?:\s+[\w ,&()/-]+)?", normalized):
        return False
    return True


async def _invoke_checker(checker: Callable, claim: Claim, title: str, text: str) -> SupportVerdict:
    result = checker(claim.text, title, text)
    if hasattr(result, "__await__"):
        result = await result
    return result if isinstance(result, SupportVerdict) else SupportVerdict.model_validate(result)


async def verify_claim(claim: Claim, bank: AuthorityBank, contract_text: str, checker: Callable) -> ClaimResult:
    if not claim.authority_ids:
        return ClaimResult(claim_id=claim.claim_id, status="unverified", reasons=["No authority IDs supplied; no legal proposition is verified."])
    authorities = []
    for authority_id in claim.authority_ids:
        authority = bank.get(authority_id)
        if not authority:
            return ClaimResult(claim_id=claim.claim_id, status="rejected", reasons=[f"Authority ID [{authority_id}] is not in the closed authority bank."])
        authorities.append(authority)
    raw_citations = extract_citations(claim.text)
    allowed_keys = {authority.key for authority in authorities}
    stray = [candidate.raw for candidate in raw_citations if candidate.normalized_key not in allowed_keys]
    if stray:
        return ClaimResult(claim_id=claim.claim_id, status="rejected", reasons=["Claim contains raw citation(s) outside its authority IDs: " + ", ".join(stray)])
    if raw_citations:
        return ClaimResult(claim_id=claim.claim_id, status="rejected", reasons=["Raw citation text is not allowed in memo claims; cite only closed-bank IDs such as [A1]."])
    if not span_in_text(claim.clause_quote, contract_text):
        return ClaimResult(claim_id=claim.claim_id, status="rejected", reasons=["Clause quote was not found verbatim in the contract."])
    authority_quotes = []
    verdicts = []
    rejected_support_quotes = False
    for authority in authorities:
        if not authority.text:
            continue
        try:
            verdict = await _invoke_checker(checker, claim, authority.title, authority.text)
        except Exception:
            continue
        quote = verdict.authority_quote
        if quote and not span_in_text(quote, authority.text):
            quote = ""
        quote_is_operative = bool(quote and _is_operative_support_quote(quote))
        if quote and not quote_is_operative:
            rejected_support_quotes = True
            quote = ""
        if quote_is_operative:
            authority_quotes.append(quote)
        verdicts.append((authority, verdict, quote, quote_is_operative))
    supported = [(authority, verdict, quote) for authority, verdict, quote, operative in verdicts if verdict.label == "supports" and quote and operative]
    if supported:
        return ClaimResult(claim_id=claim.claim_id, status="verified", reasons=[v.rationale for _, v, _ in supported], authority_quotes=[quote for _, _, quote in supported])
    if not any(a.text for a in authorities) and any(a.status == "existence-only" or not a.text for a in authorities):
        return ClaimResult(claim_id=claim.claim_id, status="existence_only", reasons=["Authority record exists, but source text or a grounded supporting passage is unavailable."], authority_quotes=authority_quotes)
    if rejected_support_quotes:
        return ClaimResult(claim_id=claim.claim_id, status="unverified", reasons=[f"The checker quotation was shorter than {MIN_SUPPORT_QUOTE_CHARS} characters, lacked sentence-ending punctuation, or was heading-only; support was not verified."], authority_quotes=authority_quotes)
    if authority_quotes:
        return ClaimResult(claim_id=claim.claim_id, status="unverified", reasons=["The checker did not find adequate support; quoted passages are grounded but may not support this claim."], authority_quotes=authority_quotes)
    return ClaimResult(claim_id=claim.claim_id, status="unverified", reasons=["No independently grounded supporting passage was returned."])


async def verify_memo(claims: list[Claim], bank: AuthorityBank, contract_text: str, checker: Callable) -> list[ClaimResult]:
    return [await verify_claim(claim, bank, contract_text, checker) for claim in claims]


def publishable(results: list[ClaimResult]) -> bool:
    # Unverified claims may be shown with an explicit warning; rejected claims may not.
    return all(result.status != "rejected" for result in results)
