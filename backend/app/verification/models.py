from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


CitationKind = Literal["us_case", "usc", "cfr", "eu_regulation", "eu_directive", "cal_code"]


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: CitationKind
    raw: str = Field(min_length=1)
    normalized_key: str = Field(min_length=1)


class Authority(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^A[1-9][0-9]*$")
    key: str
    kind: CitationKind
    title: str
    source: str
    url: str
    text: str | None = None
    retrieved_at: str | None = None
    status: Literal["resolved", "existence-only"] = "existence-only"


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str
    text: str
    authority_ids: list[str] = Field(default_factory=list)
    clause_quote: str


class SupportVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Literal["supports", "partial", "not_supported"]
    authority_quote: str = ""
    rationale: str


class ClaimResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str
    status: Literal["verified", "existence_only", "unverified", "rejected"]
    reasons: list[str] = Field(default_factory=list)
    authority_quotes: list[str] = Field(default_factory=list)


class MemoClaim(Claim):
    result: ClaimResult | None = None


class VerifiedMemo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    executive_summary: str
    claims: list[MemoClaim]
    coverage_gaps: list[str] = Field(default_factory=list)
    removed_claims: list[ClaimResult] = Field(default_factory=list)
    notice: str = "Not legal advice. Consult qualified counsel."
