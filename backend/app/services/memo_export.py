"""Generate DOCX and PDF bytes without creating temporary files."""
from html import escape
from io import BytesIO
from docx import Document
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from app.agents.risk_models import FinalMemo


def _memo(value: dict | FinalMemo) -> FinalMemo:
    return value if isinstance(value, FinalMemo) else FinalMemo.model_validate(value)


def memo_to_docx(value: dict | FinalMemo) -> bytes:
    memo = _memo(value)
    doc = Document()
    doc.add_heading(memo.title, 0)
    doc.add_paragraph(memo.notice)
    doc.add_heading("Executive summary", level=1)
    doc.add_paragraph(memo.executive_summary)
    doc.add_heading("Risks", level=1)
    for index, risk in enumerate(memo.risks, 1):
        doc.add_heading(f"{index}. {risk.title} — {risk.severity.upper()}", level=2)
        doc.add_paragraph(f"Clause IDs: {', '.join(risk.clause_ids)}")
        doc.add_paragraph(f"Exact source quote: {' | '.join(risk.exact_quotes)}")
        doc.add_paragraph(f"Why non-obvious: {risk.why_non_obvious}")
        doc.add_paragraph(f"Jurisdiction assumption: {risk.jurisdiction_assumption}")
        doc.add_paragraph(f"Suggested mitigation clause: {risk.suggested_mitigation_clause}")
        doc.add_paragraph(f"Authorities: {', '.join(f'[{authority_id}]' for authority_id in risk.authority_ids) or 'Document-only'}")
    doc.add_heading("Claims and verification", level=1)
    for claim in memo.claims:
        result = claim.result
        label = result.status.replace("_", " ").title() if result else "Unverified"
        doc.add_paragraph(f"{claim.claim_id} — {label}: {claim.text}")
        if result:
            for quote in result.authority_quotes:
                doc.add_paragraph(f"Authority quote: {quote}", style="Quote")
    doc.add_heading("Authority bank", level=1)
    for authority in memo.authority_bank:
        doc.add_paragraph(f"[{authority.id}] {authority.title} — {authority.status}. {authority.url}")
        if authority.retrieved_at:
            doc.add_paragraph(f"Retrieved: {authority.retrieved_at}")
    doc.add_heading("Coverage gaps", level=1)
    for gap in memo.coverage_gaps:
        doc.add_paragraph(gap, style="List Bullet")
    if memo.removed_claims:
        doc.add_heading("Removed for failed verification", level=1)
        for claim in memo.removed_claims:
            doc.add_paragraph(f"{claim.claim_id}: {'; '.join(claim.reasons)}", style="List Bullet")
    doc.add_heading("Methodology", level=1)
    doc.add_paragraph(memo.methodology)
    doc.add_paragraph(memo.notice)
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def memo_to_pdf(value: dict | FinalMemo) -> bytes:
    memo = _memo(value)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=0.7*inch, leftMargin=0.7*inch, topMargin=0.65*inch, bottomMargin=0.65*inch, title=memo.title)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="MemoTitle", parent=styles["Title"], alignment=TA_CENTER, textColor=colors.HexColor("#125c4f")))
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8.5, leading=11))
    story = [Paragraph(escape(memo.title), styles["MemoTitle"]), Paragraph(f"<b>{escape(memo.notice)}</b>", styles["BodyText"]), Spacer(1, 10)]
    story.extend([Paragraph("Executive summary", styles["Heading1"]), Paragraph(escape(memo.executive_summary), styles["BodyText"]), Spacer(1, 8)])
    story.append(Paragraph("Risks", styles["Heading1"]))
    for index, risk in enumerate(memo.risks, 1):
        story.append(Paragraph(f"{index}. {escape(risk.title)} — {escape(risk.severity.upper())}", styles["Heading2"]))
        story.append(Paragraph(f"<b>Clauses:</b> {escape(', '.join(risk.clause_ids))}", styles["BodyText"]))
        for label, text in (("Exact quote", " | ".join(risk.exact_quotes)), ("Why non-obvious", risk.why_non_obvious), ("Jurisdiction assumption", risk.jurisdiction_assumption), ("Mitigation clause", risk.suggested_mitigation_clause)):
            story.append(Paragraph(f"<b>{escape(label)}:</b> {escape(text)}", styles["BodyText"]))
        story.append(Paragraph(f"<b>Authorities:</b> {escape(', '.join(f'[{auth_id}]' for auth_id in risk.authority_ids) or 'Document-only')}", styles["BodyText"]))
        story.append(Spacer(1, 8))
    story.append(Paragraph("Claims and verification", styles["Heading1"]))
    for claim in memo.claims:
        status = claim.result.status.replace("_", " ").title() if claim.result else "Unverified"
        story.append(Paragraph(f"<b>{escape(claim.claim_id)} · {escape(status)}</b>: {escape(claim.text)}", styles["BodyText"]))
        if claim.result:
            for quote in claim.result.authority_quotes:
                story.append(Paragraph(f"<i>Authority quote: {escape(quote)}</i>", styles["Small"]))
    story.append(Paragraph("Authority bank", styles["Heading1"]))
    for authority in memo.authority_bank:
        story.append(Paragraph(f"<b>[{escape(authority.id)}] {escape(authority.title)}</b> — {escape(authority.status)}. {escape(authority.url)}", styles["Small"]))
    story.append(Paragraph("Coverage gaps", styles["Heading1"]))
    for gap in memo.coverage_gaps:
        story.append(Paragraph(f"• {escape(gap)}", styles["BodyText"]))
    if memo.removed_claims:
        story.append(Paragraph("Removed for failed verification", styles["Heading1"]))
        for claim in memo.removed_claims:
            story.append(Paragraph(f"{escape(claim.claim_id)}: {escape('; '.join(claim.reasons))}", styles["BodyText"]))
    story.extend([Paragraph("Methodology", styles["Heading1"]), Paragraph(escape(memo.methodology), styles["BodyText"]), Spacer(1, 12), Paragraph(f"<b>{escape(memo.notice)}</b>", styles["BodyText"])])
    doc.build(story)
    return buffer.getvalue()
