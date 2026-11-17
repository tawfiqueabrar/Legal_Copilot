from io import BytesIO
from docx import Document
import pymupdf
from app.ingestion.parse import ingest_document


def test_txt_ingestion_in_memory_and_segmentation():
    parsed = ingest_document(b"1. Scope\n\nProvider shall provide support.", "text/plain", "sample.txt")
    assert parsed.text.startswith("1. Scope")
    assert parsed.clauses[0].id == "C1"


def test_docx_ingestion_includes_paragraphs_and_table_text():
    doc = Document()
    doc.add_paragraph("1. Services")
    doc.add_paragraph("Provider will host the service.")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Controller"
    table.cell(0, 1).text = "Customer"
    data = BytesIO()
    doc.save(data)
    parsed = ingest_document(data.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "agreement.docx")
    assert "Provider will host" in parsed.text
    assert "Controller | Customer" in parsed.text


def test_pdf_text_layer_and_ocr_only_for_textless_pages():
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "1. Scope\nCustomer Data means all personal information.")
    page = pdf.new_page()
    page.insert_text((72, 72), " ")
    data = pdf.tobytes()
    pdf.close()
    calls = []
    parsed = ingest_document(data, "application/pdf", "contract.pdf", ocr=lambda image: calls.append(image.size) or "2. Term\nAuto-renews annually.")
    assert len(calls) == 1
    assert "Customer Data" in parsed.page_texts[0]
    assert "Auto-renews annually" in parsed.page_texts[1]
    assert any(clause.page == 2 for clause in parsed.clauses)
