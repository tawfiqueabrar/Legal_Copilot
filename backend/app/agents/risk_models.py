from typing import Literal
from pydantic import BaseModel, Field, ConfigDict
from app.verification.models import Claim, SupportVerdict, Authority, MemoClaim, ClaimResult


class JurisdictionFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    governing_law: str = "Unclear"
    venue: str = "Unclear"
    party_locations: list[str] = Field(default_factory=list)
    data_subject_regions: list[str] = Field(default_factory=list)
    gap: str | None = None


class VisionExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_text: str = ""
    page_texts: list[str] = Field(default_factory=list)
    document_kind: Literal["contract", "court_notice", "other"] = "other"
    parties: list[str] = Field(default_factory=list)
    deadlines: list[str] = Field(default_factory=list)


class RiskFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    risk_id: str
    title: str
    severity: Literal["critical", "high", "medium", "low"]
    clause_ids: list[str] = Field(min_length=1)
    exact_quotes: list[str] = Field(min_length=1)
    why_non_obvious: str
    jurisdiction_assumption: str
    suggested_mitigation_clause: str
    search_queries: list[str] = Field(default_factory=list)


class RiskScan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    risks: list[RiskFinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DraftMemo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = "Legal Memorandum"
    executive_summary: str
    claims: list[Claim] = Field(default_factory=list)
    coverage_gaps: list[str] = Field(default_factory=list)


class MemoRisk(RiskFinding):
    authority_ids: list[str] = Field(default_factory=list)
    pages: list[int] = Field(default_factory=list)


class FinalMemo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = "Legal Memorandum"
    executive_summary: str
    risks: list[MemoRisk] = Field(default_factory=list)
    clauses: list[dict] = Field(default_factory=list)
    claims: list[MemoClaim] = Field(default_factory=list)
    authority_bank: list[Authority] = Field(default_factory=list)
    coverage_gaps: list[str] = Field(default_factory=list)
    removed_claims: list[ClaimResult] = Field(default_factory=list)
    methodology: str = "Authorities are resolved against source records; each claim is independently checked against quoted source text."
    notice: str = "Not legal advice. Consult qualified counsel."


__all__ = ["JurisdictionFinding", "VisionExtraction", "RiskFinding", "RiskScan", "DraftMemo", "MemoRisk", "FinalMemo", "SupportVerdict"]
