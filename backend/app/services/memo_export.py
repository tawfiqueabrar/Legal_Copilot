"""Generate preliminary assessment DOCX/PDF bytes without creating temporary files."""
from html import escape
from io import BytesIO

from docx import Document
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

from app.agents.risk_models import FinalMemo
from app.services.preliminary_report import status_label


def _memo(value: dict | FinalMemo) -> FinalMemo:
    return value if isinstance(value, FinalMemo) else FinalMemo.model_validate(value)


def _docx_risk(doc: Document, index: int, risk) -> None:
    doc.add_heading(f"{index}. {risk.title} — {risk.severity.upper()}", level=2)
    doc.add_heading("Contract evidence", level=3)
    for evidence in risk.contract_evidence:
        doc.add_paragraph(f"Section {evidence.section} ({evidence.clause_id}): {evidence.quote}", style="Quote")
    doc.add_heading("Why this may matter", level=3)
    doc.add_paragraph(risk.why_may_matter)
    doc.add_heading("Legal reference", level=3)
    if risk.source_not_loaded:
        doc.add_paragraph("Source not loaded. No legal proposition is cited or paraphrased from an unavailable source.")
    for reference in risk.legal_references:
        doc.add_paragraph(f"[{reference.authority_id}] — {status_label(reference.status)}")
        if reference.support_quotes:
            for quote in reference.support_quotes:
                doc.add_paragraph(f"Support-check quote: {quote}", style="Quote")
        else:
            doc.add_paragraph("No support-check quote was returned.")
    doc.add_heading("Suggested action", level=3)
    doc.add_paragraph(risk.suggested_mitigation_clause)
    doc.add_paragraph(risk.citation_check_line)


def _pdf_risk(story: list, styles, index: int, risk) -> None:
    story.append(Paragraph(f"{index}. {escape(risk.title)} — {escape(risk.severity.upper())}", styles["Heading2"]))
    story.append(Paragraph("<b>Contract evidence</b>", styles["Heading3"]))
    for evidence in risk.contract_evidence:
        story.append(Paragraph(f"<b>Section {escape(evidence.section)} ({escape(evidence.clause_id)}):</b> {escape(evidence.quote)}", styles["BodyText"]))
    story.append(Paragraph("<b>Why this may matter</b>", styles["Heading3"]))
    story.append(Paragraph(escape(risk.why_may_matter), styles["BodyText"]))
    story.append(Paragraph("<b>Legal reference</b>", styles["Heading3"]))
    if risk.source_not_loaded:
        story.append(Paragraph("Source not loaded. No legal proposition is cited or paraphrased from an unavailable source.", styles["BodyText"]))
    for reference in risk.legal_references:
        story.append(Paragraph(f"[{escape(reference.authority_id)}] — {escape(status_label(reference.status))}", styles["BodyText"]))
        if reference.support_quotes:
            for quote in reference.support_quotes:
                story.append(Paragraph(f"<i>Support-check quote: {escape(quote)}</i>", styles["Small"]))
        else:
            story.append(Paragraph("No support-check quote was returned.", styles["Small"]))
    story.append(Paragraph("<b>Suggested action</b>", styles["Heading3"]))
    story.append(Paragraph(escape(risk.suggested_mitigation_clause), styles["BodyText"]))
    story.append(Paragraph(f"<b>{escape(risk.citation_check_line)}</b>", styles["BodyText"]))
    story.append(Spacer(1, 8))


def _document_facts_lines(memo: FinalMemo) -> list[str]:
    facts = memo.document_facts or {}
    rows = []
    if facts.get("document_kind"):
        rows.append(f"Document type: {facts['document_kind']}")
    rows.extend(f"Party extracted from image: {party}" for party in facts.get("parties", []))
    rows.extend(f"Potential deadline to confirm: {deadline}" for deadline in facts.get("deadlines", []))
    return rows


def memo_to_docx(value: dict | FinalMemo) -> bytes:
    memo = _memo(value)
    doc = Document()
    doc.add_heading(memo.title, 0)
    doc.add_paragraph(f"Document name: {memo.document_name or 'Unavailable'}")
    doc.add_paragraph(memo.assessment_line)
    doc.add_paragraph(memo.notice)
    fact_lines = _document_facts_lines(memo)
    if fact_lines:
        doc.add_heading("Vision-extracted document details", level=1)
        doc.add_paragraph("Confirm extracted names and dates against the original document.")
        for line in fact_lines:
            doc.add_paragraph(line, style="List Bullet")

    doc.add_heading("Legal sources in scope", level=1)
    if memo.legal_sources_in_scope:
        for source in memo.legal_sources_in_scope:
            retrieved = f" Retrieved: {source.retrieved_at}" if source.retrieved_at else ""
            doc.add_paragraph(f"[{source.authority_id}] {source.title} — {source.source}. {source.url}{retrieved}", style="List Bullet")
    else:
        doc.add_paragraph("No non-empty legal source text was loaded for this assessment.")

    doc.add_heading("Not assessed", level=1)
    if memo.not_assessed:
        for item in memo.not_assessed:
            doc.add_paragraph(f"{item.name}: {item.note}", style="List Bullet")
    else:
        doc.add_paragraph("No additional unassessed jurisdiction or regime was detected from the available text.")

    doc.add_heading("Executive summary", level=1)
    doc.add_paragraph(memo.executive_summary)
    doc.add_heading("Risks", level=1)
    for index, risk in enumerate(memo.risks, 1):
        _docx_risk(doc, index, risk)

    doc.add_heading("Claims and verification", level=1)
    for claim in memo.claims:
        result = claim.result
        label = status_label(result.status) if result else "Unverified"
        doc.add_paragraph(f"{claim.claim_id} — {label}: {claim.text}")
        if result:
            for quote in result.authority_quotes:
                doc.add_paragraph(f"Support-check quote: {quote}", style="Quote")

    doc.add_heading("Coverage gaps", level=1)
    if memo.coverage_gaps:
        for gap in memo.coverage_gaps:
            doc.add_paragraph(gap, style="List Bullet")
    else:
        doc.add_paragraph("No additional coverage gaps were recorded.")
    if memo.removed_claims:
        doc.add_heading("Removed for failed verification", level=1)
        for claim in memo.removed_claims:
            doc.add_paragraph(f"{claim.claim_id}: {'; '.join(claim.reasons)}", style="List Bullet")

    doc.add_heading("Evidence gaps", level=1)
    if memo.evidence_gaps:
        for gap in memo.evidence_gaps:
            clauses = ", ".join(gap.clause_ids) or "document-level"
            affected = ", ".join(gap.affected_risk_ids) or "No specific finding linked"
            doc.add_paragraph(f"{gap.marker} — {clauses}. {gap.note} Affected findings: {affected}.", style="List Bullet")
    else:
        doc.add_paragraph("No redaction, missing-content, or truncation markers were detected in the extracted text.")

    doc.add_heading("Methodology", level=1)
    doc.add_paragraph(memo.methodology)
    doc.add_paragraph(memo.notice)
    doc.add_paragraph(memo.footer)
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def memo_to_pdf(value: dict | FinalMemo) -> bytes:
    memo = _memo(value)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=0.7 * inch, leftMargin=0.7 * inch, topMargin=0.65 * inch, bottomMargin=0.65 * inch, title=memo.title)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="MemoTitle", parent=styles["Title"], alignment=TA_CENTER, textColor=colors.HexColor("#125c4f")))
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8.5, leading=11))
    story = [
        Paragraph(escape(memo.title), styles["MemoTitle"]),
        Paragraph(f"<b>Document name:</b> {escape(memo.document_name or 'Unavailable')}", styles["BodyText"]),
        Paragraph(f"<b>{escape(memo.assessment_line)}</b>", styles["BodyText"]),
        Paragraph(f"<b>{escape(memo.notice)}</b>", styles["BodyText"]),
        Spacer(1, 10),
        Paragraph("Legal sources in scope", styles["Heading1"]),
    ]
    fact_lines = _document_facts_lines(memo)
    if fact_lines:
        story.extend([Paragraph("Vision-extracted document details", styles["Heading1"]), Paragraph("Confirm extracted names and dates against the original document.", styles["BodyText"])])
        story.extend(Paragraph(escape(line), styles["BodyText"]) for line in fact_lines)
    if memo.legal_sources_in_scope:
        for source in memo.legal_sources_in_scope:
            retrieved = f" Retrieved: {source.retrieved_at}" if source.retrieved_at else ""
            story.append(Paragraph(f"[{escape(source.authority_id)}] {escape(source.title)} — {escape(source.source)}. {escape(source.url)}{escape(retrieved)}", styles["Small"]))
    else:
        story.append(Paragraph("No non-empty legal source text was loaded for this assessment.", styles["BodyText"]))

    story.append(Paragraph("Not assessed", styles["Heading1"]))
    if memo.not_assessed:
        for item in memo.not_assessed:
            story.append(Paragraph(f"<b>{escape(item.name)}:</b> {escape(item.note)}", styles["BodyText"]))
    else:
        story.append(Paragraph("No additional unassessed jurisdiction or regime was detected from the available text.", styles["BodyText"]))

    story.extend([Paragraph("Executive summary", styles["Heading1"]), Paragraph(escape(memo.executive_summary), styles["BodyText"]), Spacer(1, 8), Paragraph("Risks", styles["Heading1"])])
    for index, risk in enumerate(memo.risks, 1):
        _pdf_risk(story, styles, index, risk)

    story.append(Paragraph("Claims and verification", styles["Heading1"]))
    for claim in memo.claims:
        status = status_label(claim.result.status) if claim.result else "Unverified"
        story.append(Paragraph(f"<b>{escape(claim.claim_id)} · {escape(status)}</b>: {escape(claim.text)}", styles["BodyText"]))
        if claim.result:
            for quote in claim.result.authority_quotes:
                story.append(Paragraph(f"<i>Support-check quote: {escape(quote)}</i>", styles["Small"]))

    story.append(Paragraph("Coverage gaps", styles["Heading1"]))
    if memo.coverage_gaps:
        for gap in memo.coverage_gaps:
            story.append(Paragraph(f"• {escape(gap)}", styles["BodyText"]))
    else:
        story.append(Paragraph("No additional coverage gaps were recorded.", styles["BodyText"]))
    if memo.removed_claims:
        story.append(Paragraph("Removed for failed verification", styles["Heading1"]))
        for claim in memo.removed_claims:
            story.append(Paragraph(f"{escape(claim.claim_id)}: {escape('; '.join(claim.reasons))}", styles["BodyText"]))

    story.append(Paragraph("Evidence gaps", styles["Heading1"]))
    if memo.evidence_gaps:
        for gap in memo.evidence_gaps:
            clauses = ", ".join(gap.clause_ids) or "document-level"
            affected = ", ".join(gap.affected_risk_ids) or "No specific finding linked"
            story.append(Paragraph(f"<b>{escape(gap.marker)} — {escape(clauses)}.</b> {escape(gap.note)} Affected findings: {escape(affected)}.", styles["BodyText"]))
    else:
        story.append(Paragraph("No redaction, missing-content, or truncation markers were detected in the extracted text.", styles["BodyText"]))

    story.extend([
        Paragraph("Methodology", styles["Heading1"]), Paragraph(escape(memo.methodology), styles["BodyText"]),
        Spacer(1, 12), Paragraph(f"<b>{escape(memo.notice)}</b>", styles["BodyText"]),
        Paragraph(escape(memo.footer), styles["BodyText"]),
    ])
    doc.build(story)
    return buffer.getvalue()
