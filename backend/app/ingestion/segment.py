"""Clause boundaries preserve original character offsets and verbatim source text."""
import re
from .models import Clause

_NUMBERED = re.compile(r"^\s*(?:(?:\d+(?:\.\d+)*\.?)(?:\s+|$)|\([A-Za-z0-9]+\)(?:\s+|$))")
_DEFINITION = re.compile(r"(?m)^\s*(?:(?:\d+(?:\.\d+)*\.?|\([A-Za-z0-9]+\))\s+)?(?:[\"“']([^\"”']{2,100})[\"”']|([A-Z][A-Za-z0-9&' -]{1,80}?))\s+means\s+(.+?)(?=(?:\n\s*\n)|$)", re.I | re.S)


def _is_heading(line: str) -> bool:
    candidate = line.strip()
    if not candidate or len(candidate) > 140:
        return False
    if _NUMBERED.match(candidate):
        return True
    letters = [char for char in candidate if char.isalpha()]
    return len(letters) >= 3 and candidate == candidate.upper() and len(candidate.split()) <= 16


def _heading_for(block: str) -> str | None:
    first = block.splitlines()[0].strip() if block.splitlines() else ""
    return first if _is_heading(first) else None


def segment_document(text: str, page_texts: list[str] | None = None) -> tuple[list[Clause], dict[str, str]]:
    """Split by legal headings and paragraph boundaries without rewriting text."""
    if not text:
        return [], {}
    boundaries = {0, len(text)}
    offset = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if _is_heading(content) and offset > 0:
            boundaries.add(offset)
        offset += len(line)
    # Paragraph splits help unnumbered agreements; heading boundaries remain preferred.
    for match in re.finditer(r"\n\s*\n+", text):
        boundaries.add(match.end())
    ordered = sorted(boundaries)
    pieces: list[tuple[int, int]] = []
    for i in range(len(ordered) - 1):
        start, end = ordered[i], ordered[i + 1]
        if text[start:end].strip():
            pieces.append((start, end))
    clauses: list[Clause] = []
    for index, (start, end) in enumerate(pieces, 1):
        raw = text[start:end]
        page = None
        # Page breaks are represented by explicit markers in the ingested text.
        before = text[:start]
        page_markers = list(re.finditer(r"\[Page\s+(\d+)\]", before, re.I))
        if page_markers:
            page = int(page_markers[-1].group(1))
        clauses.append(Clause(id=f"C{index}", heading=_heading_for(raw), text=raw, start=start, end=end, page=page))
    definitions: dict[str, str] = {}
    for match in _DEFINITION.finditer(text):
        definitions[(match.group(1) or match.group(2)).strip()] = match.group(3).strip().rstrip(".;")
    if page_texts and not any(clause.page for clause in clauses):
        # If the caller provided page text but no markers, assign by offsets against the same joined representation.
        cursor = 0
        for clause in clauses:
            for page_index, page_text in enumerate(page_texts, 1):
                if page_text and clause.start >= cursor and clause.start < cursor + len(page_text):
                    clause.page = page_index
                    break
                cursor += len(page_text) + 1
            cursor = 0
    return clauses, definitions
