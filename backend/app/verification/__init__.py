"""Closed-set legal citation and claim verification."""

from .bank import AuthorityBank
from .extract import CitationCandidate, extract_citations, normalize_citation, span_in_text
from .models import Authority, Claim, ClaimResult, Citation, SupportVerdict
from .verifier import publishable, verify_claim, verify_memo

__all__ = ["AuthorityBank", "Authority", "Claim", "ClaimResult", "Citation", "SupportVerdict", "CitationCandidate", "extract_citations", "normalize_citation", "span_in_text", "verify_claim", "verify_memo", "publishable"]
