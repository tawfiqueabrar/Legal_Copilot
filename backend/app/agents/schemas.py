from typing import Literal
from pydantic import BaseModel, Field


class DocumentFact(BaseModel):
    kind: Literal["contract", "court_notice", "other"] = "other"
    title: str = "Uploaded document"
    jurisdiction: str | None = None
    parties: list[str] = Field(default_factory=list)
    deadlines: list[str] = Field(default_factory=list)
    clauses: list[dict] = Field(default_factory=list)


class Citation(BaseModel):
    citation_text: str
    query: str
    source: Literal["courtlistener", "eurlex", "none"] = "none"
    status: Literal["verified_record", "unverified", "proprietary_clause"] = "unverified"
    matched_title: str | None = None
    url: str | None = None
    verification_note: str


class Risk(BaseModel):
    id: str
    title: str
    severity: Literal["critical", "high", "medium", "low"]
    issue: str
    rule: str = "No external rule asserted; document-only issue spotting."
    analysis: str = ""
    conclusion: str = ""
    quote: str | None = None
    page: int | None = None
    bbox: list[float] | None = None
    section: str | None = None
    why_non_obvious: str
    citation: Citation | None = None
    mitigation: str


class Memo(BaseModel):
    title: str = "Legal Memorandum"
    jurisdiction: str = "Unspecified"
    disclaimer: str = "AI-generated issue spotting only; obtain advice from qualified counsel."
    executive_summary: str
    risks: list[Risk]
    conclusion: str
    rule: str = "Only matched source records are identified; their legal propositions require counsel review."


class SynthesisDraft(BaseModel):
    executive_summary: str
    conclusion: str
    mitigations: dict[str, str] = Field(default_factory=dict)


class AnalysisState(BaseModel):
    session_id: str
    document_text: str = ""
    page_texts: list[str] = Field(default_factory=list)
    document: DocumentFact = Field(default_factory=DocumentFact)
    risks: list[Risk] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    memo: Memo | None = None
    iteration: int = 0
    errors: list[str] = Field(default_factory=list)
    progress: list[dict] = Field(default_factory=list)
