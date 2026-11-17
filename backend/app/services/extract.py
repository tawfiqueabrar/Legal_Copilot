from io import BytesIO
from pypdf import PdfReader


def extract_document(data: bytes, content_type: str, filename: str) -> tuple[str, list[str]]:
    """Extract text with page attribution. OCR/vision is handled by Gemini for image PDFs."""
    if content_type == "application/pdf" or filename.lower().endswith(".pdf"):
        reader = PdfReader(BytesIO(data), strict=False)
        pages = [(page.extract_text() or "") for page in reader.pages]
        return "\n\n".join(f"[Page {i + 1}]\n{text}" for i, text in enumerate(pages)), pages
    if content_type.startswith("image/"):
        return "", []
    try:
        return data.decode("utf-8"), [data.decode("utf-8")]
    except UnicodeDecodeError as exc:
        raise ValueError("Unsupported document format. Upload a PDF, image, or UTF-8 text file.") from exc
