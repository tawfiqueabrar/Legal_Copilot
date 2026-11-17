"""In-memory PDF/DOCX/TXT ingestion with Tesseract only for textless PDF pages."""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import shutil
from typing import Callable
from docx import Document as DocxDocument
import pymupdf
from PIL import Image
from .models import ParsedDocument
from .segment import segment_document


def _ocr_page(page, ocr: Callable | None) -> str:
    pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
    image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    if ocr:
        return ocr(image) or ""
    if not shutil.which("tesseract"):
        return ""
    try:
        import pytesseract
        return pytesseract.image_to_string(image) or ""
    except Exception:
        return ""


def ingest_document(data: bytes, content_type: str, filename: str, *, ocr: Callable | None = None) -> ParsedDocument:
    name = Path(filename or "document").name
    suffix = Path(name).suffix.lower()
    warnings: list[str] = []
    pages: list[str] = []
    if content_type == "application/pdf" or suffix == ".pdf":
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            for page_number, page in enumerate(pdf, 1):
                text = page.get_text("text").strip()
                if not text:
                    text = _ocr_page(page, ocr).strip()
                    if not text:
                        warnings.append(f"Page {page_number} had no text layer and OCR returned no text.")
                pages.append(text)
        full_text = "\n\n".join(f"[Page {index}]\n{text}" for index, text in enumerate(pages, 1))
        detected_type = "application/pdf"
    elif content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or suffix == ".docx":
        doc = DocxDocument(BytesIO(data))
        blocks = [paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                blocks.append(" | ".join(cell.text.strip() for cell in row.cells))
        full_text = "\n\n".join(blocks)
        pages = [full_text]
        detected_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif content_type.startswith("text/") or suffix == ".txt":
        full_text = data.decode("utf-8-sig")
        pages = [full_text]
        detected_type = "text/plain"
    else:
        raise ValueError("Unsupported document format; upload PDF, DOCX, or UTF-8 TXT.")
    clauses, definitions = segment_document(full_text, pages)
    return ParsedDocument(filename=name, content_type=detected_type, text=full_text,
                          page_texts=pages, clauses=clauses, definitions=definitions, warnings=warnings)
