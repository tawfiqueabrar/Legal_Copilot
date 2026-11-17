"""Deterministic citation extraction and quote matching; no model calls."""
from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class CitationCandidate:
    kind: str
    raw: str
    normalized_key: str
    start: int
    end: int


_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("us_case", re.compile(r"\b\d{1,4}\s+U\.?\s*S\.?\s+\d{1,5}\b", re.I)),
    ("us_case", re.compile(r"\b\d{1,4}\s+F\.?\s*(?:2d|3d|4th|Supp\.?\s*(?:2d|3d)?|App['’]?x)\s+\d{1,5}\b", re.I)),
    ("usc", re.compile(r"\b\d{1,3}\s+U\.?\s*S\.?\s*C\.?\s*§{1,2}\s*\d+[A-Za-z0-9.-]*(?:\s*\([^)]{1,20}\))*", re.I)),
    ("cfr", re.compile(r"\b\d{1,3}\s+C\.?\s*F\.?\s*R\.?\s*§{1,2}\s*\d+(?:\.\d+)*(?:\s*\([^)]{1,20}\))*", re.I)),
    ("eu_regulation", re.compile(r"\bRegulation\s*\(\s*EU\s*\)\s*\d{4}\s*/\s*\d{1,5}\b", re.I)),
    ("eu_directive", re.compile(r"\bDirective\s*(?:\(\s*EU\s*\)\s*)?\d{4}\s*/\s*\d{1,5}\b", re.I)),
    ("cal_code", re.compile(r"\bCal\.?\s+Bus(?:iness)?\.?\s*(?:&|and)\s*Prof(?:essions)?\.?\s+Code\s*§{1,2}\s*\d+(?:\.\d+)*(?:\s*\([^)]{1,20}\))*", re.I)),
]


def _canonical_spaces(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("§§", "§")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_citation(raw: str, kind: str | None = None) -> str:
    value = _canonical_spaces(raw)
    value = re.sub(r"\s*\([^)]{1,20}\)", "", value)  # subsections do not alter the checked section key
    if kind == "us_case" or re.search(r"\b(?:U\.?\s*S\.?|F\.)", value, re.I):
        reporter = re.sub(r"\s+", " ", value.upper())
        reporter = re.sub(r"U\.?\s*S\.?", "U.S.", reporter)
        reporter = re.sub(r"F\.?\s*(2D|3D|4TH|SUPP\.?\s*(?:2D|3D)?|APP['’]?X)", lambda m: "F." + re.sub(r"\s+", "", m.group(1)).replace("SUPP", "Supp."), reporter)
        return re.sub(r"\s+", " ", reporter).strip()
    if kind == "usc" or "U.S.C" in value.upper():
        m = re.search(r"(\d+)\s+U\.?\s*S\.?\s*C\.?\s*§{1,2}\s*(\d+[A-Za-z0-9.-]*)", value, re.I)
        return f"{m.group(1)} U.S.C. § {m.group(2)}" if m else value.casefold()
    if kind == "cfr" or "C.F.R" in value.upper():
        m = re.search(r"(\d+)\s+C\.?\s*F\.?\s*R\.?\s*§{1,2}\s*(\d+(?:\.\d+)*)", value, re.I)
        return f"{m.group(1)} C.F.R. § {m.group(2)}" if m else value.casefold()
    if kind == "eu_regulation":
        m = re.search(r"(\d{4})\s*/\s*(\d+)", value)
        return f"EU REGULATION {m.group(1)}/{m.group(2)}" if m else value.casefold()
    if kind == "eu_directive":
        m = re.search(r"(\d{4})\s*/\s*(\d+)", value)
        return f"EU DIRECTIVE {m.group(1)}/{m.group(2)}" if m else value.casefold()
    if kind == "cal_code" or "BUS" in value.upper():
        m = re.search(r"§{1,2}\s*(\d+(?:\.\d+)*)", value)
        return f"CAL BUS. & PROF. CODE § {m.group(1)}" if m else value.casefold()
    return _canonical_spaces(value).casefold()


def extract_citations(text: str) -> list[CitationCandidate]:
    found: list[CitationCandidate] = []
    occupied: list[tuple[int, int]] = []
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            if any(match.start() < end and match.end() > start for start, end in occupied):
                continue
            raw = match.group(0)
            found.append(CitationCandidate(kind, raw, normalize_citation(raw, kind), match.start(), match.end()))
            occupied.append((match.start(), match.end()))
    return sorted(found, key=lambda item: (item.start, item.end))


def _quote_normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.translate(str.maketrans({"“": '"', "”": '"', "„": '"', "‟": '"', "‘": '"', "’": '"', "‚": '"', "‛": '"', "'": '"'}))
    return " ".join(value.casefold().split())


def span_in_text(span: str, text: str) -> bool:
    if not span or not text:
        return False
    return _quote_normalize(span) in _quote_normalize(text)
