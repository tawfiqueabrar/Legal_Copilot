from io import BytesIO
from docx import Document
from pypdf import PdfReader
from app.agents.risk_models import ContractEvidence, EvidenceGap, FinalMemo, LegalSource, MemoRisk, RiskLegalReference, NotAssessedItem
from app.verification.models import Authority, ClaimResult, MemoClaim
from app.services.memo_export import memo_to_docx, memo_to_pdf


def sample_memo():
    return FinalMemo(
        title="Preliminary Contract Risk Assessment",
        document_name="sample.txt",
        assessment_line="Potential risks found; no legal violation established",
        legal_sources_in_scope=[LegalSource(authority_id="A1", title="Authority record", source="test", url="https://example.test")],
        not_assessed=[NotAssessedItem(name="Test jurisdiction", note="The source library lacks loaded text for this jurisdiction or regime; it was not assessed.")],
        executive_summary="The agreement contains a quote-grounded risk.",
        risks=[MemoRisk(risk_id="R1", title="Cap carve-out", severity="high", clause_ids=["C1"], exact_quotes=["indemnity is unlimited"], why_non_obvious="The cap is undercut elsewhere.", why_may_matter="This may affect risk allocation if the trigger occurs.", jurisdiction_assumption="Unclear", suggested_mitigation_clause="Bring indemnity under the cap.", authority_ids=["A1"], contract_evidence=[ContractEvidence(clause_id="C1", section="9.3", quote="indemnity is unlimited")], legal_references=[RiskLegalReference(authority_id="A1", status="existence_only")], citation_status="existence_only", applicability_note="Applicability conditional.", citation_check_line="Citation check: Existence-only — Applicability conditional.")],
        claims=[MemoClaim(claim_id="M1", text="This clause may create uncapped exposure if the trigger occurs [A1].", authority_ids=["A1"], clause_quote="indemnity is unlimited", result=ClaimResult(claim_id="M1", status="existence_only", reasons=["Authority record exists; text unavailable."]))],
        authority_bank=[Authority(id="A1", key="synthetic:record", kind="us_case", title="Authority record", source="test", url="https://example.test", status="existence-only")],
        coverage_gaps=["Jurisdiction unclear."],
        removed_claims=[ClaimResult(claim_id="M2", status="rejected", reasons=["Quote mismatch."])],
        evidence_gaps=[EvidenceGap(marker="[REDACTED]", clause_ids=["C1"], affected_risk_ids=["R1"], note="The marked material may affect findings.")],
        footer="This report does not establish an actual violation or provide a final legal opinion.",
    )


def test_docx_export_is_in_memory_and_contains_verification_sections():
    data = memo_to_docx(sample_memo())
    doc = Document(BytesIO(data))
    text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "Not legal advice" in text
    assert "Removed for failed verification" in text
    assert "Existence-only" in text
    assert "Document name: sample.txt" in text
    assert "Potential risks found; no legal violation established" in text
    assert "Section 9.3" in text
    assert "Citation check: Existence-only" in text
    assert "[REDACTED]" in text
    assert "This report does not establish an actual violation" in text


def test_pdf_export_is_valid_and_contains_memo_notice():
    data = memo_to_pdf(sample_memo())
    reader = PdfReader(BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert len(reader.pages) >= 1
    assert "Not legal advice" in text
    assert "Coverage gaps" in text
    assert "Legal sources in scope" in text
    assert "Not assessed" in text
    assert "Evidence gaps" in text
    assert "Citation check: Existence-only" in text
    assert "This report does not establish an actual violation" in text
