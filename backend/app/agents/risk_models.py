from typing import Literal
from pydantic import BaseModel, Field, ConfigDict
from app.verification.models import Claim, SupportVerdict, Authority, MemoClaim, ClaimResult


class JurisdictionFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    governing_law: str = "Unclear"
    venue: str = "Unclear"
    party_locations: list[str] = Field(default_factory=list)
    data_subject_regions: list[str] = Field(default_factory=list)
    subject_hints: list[str] = Field(default_factory=list)
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
    contract_evidence: list["ContractEvidence"] = Field(default_factory=list)
    why_may_matter: str = ""
    legal_references: list["RiskLegalReference"] = Field(default_factory=list)
    citation_status: Literal["verified", "existence_only", "unverified", "rejected"] = "unverified"
    applicability_note: str = "Applicability conditional; confirm the relevant facts and jurisdiction."
    citation_check_line: str = "Citation check: Unverified — Applicability conditional."
    source_not_loaded: bool = False


class ContractEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clause_id: str
    section: str
    quote: str


class RiskLegalReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_id: str = Field(pattern=r"^A[1-9][0-9]*$")
    status: Literal["verified", "existence_only", "unverified", "rejected"]
    support_quotes: list[str] = Field(default_factory=list)


class LegalSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_id: str = Field(pattern=r"^A[1-9][0-9]*$")
    title: str
    source: str
    url: str
    retrieved_at: str | None = None


class NotAssessedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    note: str


class EvidenceGap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    marker: str
    clause_ids: list[str] = Field(default_factory=list)
    affected_risk_ids: list[str] = Field(default_factory=list)
    note: str


MemoRisk.model_rebuild()


class FinalMemo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = "Preliminary Contract Risk Assessment"
    document_name: str = ""
    assessment_line: str = "Potential risks found; no legal violation established"
    legal_sources_in_scope: list[LegalSource] = Field(default_factory=list)
    not_assessed: list[NotAssessedItem] = Field(default_factory=list)
    executive_summary: str
    risks: list[MemoRisk] = Field(default_factory=list)
    clauses: list[dict] = Field(default_factory=list)
    claims: list[MemoClaim] = Field(default_factory=list)
    authority_bank: list[Authority] = Field(default_factory=list)
    coverage_gaps: list[str] = Field(default_factory=list)
    removed_claims: list[ClaimResult] = Field(default_factory=list)
    evidence_gaps: list[EvidenceGap] = Field(default_factory=list)
    methodology: str = "Authorities are resolved against source records; each claim is independently checked against quoted source text."
    notice: str = "Not legal advice. Consult qualified counsel."
    footer: str = "This report does not establish an actual violation or provide a final legal opinion."
    document_facts: dict = Field(default_factory=dict)
    analysis_metadata: dict = Field(default_factory=dict)


__all__ = ["JurisdictionFinding", "VisionExtraction", "RiskFinding", "RiskScan", "DraftMemo", "MemoRisk", "FinalMemo", "SupportVerdict"]
