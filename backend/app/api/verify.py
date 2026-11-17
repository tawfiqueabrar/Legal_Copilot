"""Citation-only probe endpoint. A source lookup never upgrades a claim to verified."""
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.api.routes import workflow
from app.verification.bank import AuthorityBank
from app.verification.extract import extract_citations
from app.verification.models import Claim, ClaimResult, SupportVerdict
from app.verification.verifier import verify_claim

router = APIRouter(tags=["verification"])


class CitationProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    citation: str = Field(min_length=1, max_length=500)


class CitationProbeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    citation: str
    normalized_key: str | None = None
    result: ClaimResult
    authority: dict | None = None


async def _citation_only_checker(claim_text: str, authority_title: str, authority_text: str) -> SupportVerdict:
    return SupportVerdict(
        label="not_supported",
        rationale="A citation lookup alone does not establish that a source supports a legal proposition.",
    )


@router.post("/verify", response_model=CitationProbeResponse)
async def verify_citation(request: CitationProbeRequest):
    candidates = extract_citations(request.citation)
    if len(candidates) != 1 or candidates[0].raw.strip() != request.citation.strip():
        return CitationProbeResponse(
            citation=request.citation,
            result=ClaimResult(
                claim_id="citation-probe",
                status="rejected",
                reasons=["Enter exactly one citation in a supported citation format."],
            ),
        )

    candidate = candidates[0]
    from app.verification.models import Citation

    citation = Citation(kind=candidate.kind, raw=candidate.raw, normalized_key=candidate.normalized_key)
    try:
        authority = await workflow.resolver.resolve(citation)
    except Exception:
        authority = None
    bank = AuthorityBank([authority] if authority else [])
    # This probe tests source resolution only. Even a resolved source receives an
    # unverified result because no substantive legal claim was submitted.
    claim = Claim(
        claim_id="citation-probe",
        text="The cited source supports the associated legal proposition.",
        authority_ids=["A1"],
        clause_quote=candidate.raw,
    )
    result = await verify_claim(claim, bank, candidate.raw, _citation_only_checker)
    return CitationProbeResponse(
        citation=request.citation,
        normalized_key=candidate.normalized_key,
        result=result,
        authority=authority.model_dump() if authority else None,
    )
