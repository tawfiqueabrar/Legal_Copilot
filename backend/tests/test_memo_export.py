from io import BytesIO
from docx import Document
from pypdf import PdfReader
from app.agents.risk_models import FinalMemo, MemoRisk
from app.verification.models import Authority, ClaimResult, MemoClaim
from app.services.memo_export import memo_to_docx, memo_to_pdf


def sample_memo():
    return FinalMemo(
        title="Legal Memorandum",
        executive_summary="The agreement contains a quote-grounded risk.",
        risks=[MemoRisk(risk_id="R1", title="Cap carve-out", severity="high", clause_ids=["C1", "C2"], exact_quotes=["indemnity is unlimited"], why_non_obvious="The cap is undercut elsewhere.", jurisdiction_assumption="Unclear", suggested_mitigation_clause="Bring indemnity under the cap.", authority_ids=["A1"])],
        claims=[MemoClaim(claim_id="M1", text="The terms create uncapped exposure [A1].", authority_ids=["A1"], clause_quote="indemnity is unlimited", result=ClaimResult(claim_id="M1", status="existence_only", reasons=["Authority record exists; text unavailable."]))],
        authority_bank=[Authority(id="A1", key="42 U.S.C. § 1983", kind="usc", title="Authority record", source="test", url="https://example.test", status="existence-only")],
        coverage_gaps=["Jurisdiction unclear."],
        removed_claims=[ClaimResult(claim_id="M2", status="rejected", reasons=["Quote mismatch."])],
    )


def test_docx_export_is_in_memory_and_contains_verification_sections():
    data = memo_to_docx(sample_memo())
    doc = Document(BytesIO(data))
    text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "Not legal advice" in text
    assert "Removed for failed verification" in text
    assert "Existence Only" in text


def test_pdf_export_is_valid_and_contains_memo_notice():
    data = memo_to_pdf(sample_memo())
    reader = PdfReader(BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert len(reader.pages) >= 1
    assert "Not legal advice" in text
    assert "Coverage gaps" in text
