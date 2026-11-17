"""Fetch the seed statutes from the official sources listed in this file.

Run from any directory with ``python scripts/fetch_statutes.py`` (inside backend).
No statute text is embedded here: only downloaded source text is written to JSON.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import ssl
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "statutes.json"
USER_AGENT = "LegalCopilot-Hackathon/1.0 (official-statute-fetch; contact: maintainers)"
TLS_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def _seeds() -> dict[str, dict[str, str | None]]:
    entries: dict[str, dict[str, str | None]] = {}
    eu_url = "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32016R0679"
    entries["EU REGULATION 2016/679"] = {
        "title": "Regulation (EU) 2016/679 (GDPR), Articles 28 and 44–46",
        "url": eu_url,
        "source": "EUR-Lex",
        "kind": "eu_regulation",
        "text": None,
        "retrieved_at": None,
    }
    for section in ("16600", "16600.5"):
        url = f"https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?sectionNum={section}.&lawCode=BPC"
        entries[f"CAL BUS. & PROF. CODE § {section}"] = {
            "title": f"California Business and Professions Code § {section}", "url": url,
            "fallback_urls": [f"https://www.law.cornell.edu/statutes/california/BPC/{section}"],
            "source": "California Legislative Information", "kind": "cal_code", "text": None, "retrieved_at": None,
        }
    us_sections = [
        (29, "206", "Fair Labor Standards Act, 29 U.S.C. § 206"),
        (29, "207", "Fair Labor Standards Act, 29 U.S.C. § 207"),
        (15, "45", "Federal Trade Commission Act, 15 U.S.C. § 45"),
        (18, "1836", "Defend Trade Secrets Act, 18 U.S.C. § 1836"),
    ]
    for title, section, label in us_sections:
        govinfo_paths = {
            (29, "206"): "chap8-sec206", (29, "207"): "chap8-sec207",
            (15, "45"): "chap2-subchapI-sec45", (18, "1836"): "partI-chap90-sec1836",
        }
        path = govinfo_paths[(title, section)]
        url = f"https://www.govinfo.gov/content/pkg/USCODE-2023-title{title}/html/USCODE-2023-title{title}-{path}.htm"
        entries[f"{title} U.S.C. § {section}"] = {
            "title": label, "url": url, "source": "Office of the Law Revision Counsel, U.S. House of Representatives",
            "kind": "usc", "text": None, "retrieved_at": None,
        }
    for section in ("1798.100", "1798.140"):
        url = f"https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?sectionNum={section}.&lawCode=CIV"
        entries[f"CAL CIV. CODE § {section}"] = {
            "title": f"California Civil Code § {section} (CCPA)", "url": url,
            "fallback_urls": [f"https://www.law.cornell.edu/statutes/california/CIV/{section}"],
            "source": "California Legislative Information", "kind": "cal_civ_code", "text": None, "retrieved_at": None,
        }
    return entries


class _TextExtractor(HTMLParser):
    """Extract visible text while excluding script/style/navigation boilerplate."""
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip_depth += 1
        if not self.skip_depth and tag in {"p", "div", "section", "article", "h1", "h2", "h3", "li", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and tag in {"p", "div", "section", "article", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)


def fetch_text(url: str, *, opener=urlopen, attempts: int = 3) -> tuple[str, str]:
    """Download official HTML with a small exponential-backoff retry budget."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
            with opener(request, timeout=30, context=TLS_CONTEXT) as response:
                payload = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
            parser = _TextExtractor()
            parser.feed(payload.decode(charset, errors="replace"))
            text = re.sub(r"[ \t\f\v]+", " ", "".join(parser.parts))
            text = re.sub(r"\n\s*\n+", "\n", text).strip()
            if len(text) < 150:
                raise ValueError("official source returned no usable statute text")
            return text, datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.5 * (2**attempt))
    raise RuntimeError(str(last_error or "unknown fetch error"))


def main() -> int:
    entries = _seeds()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    for key, entry in entries.items():
        candidates = [entry["url"], *entry.pop("fallback_urls", [])]
        failure: Exception | None = None
        for source_url in candidates:
            try:
                downloaded, retrieved_at = fetch_text(source_url or "")
                if key == "EU REGULATION 2016/679":
                    # Retain the exact articles requested, directly from the fetched EUR-Lex text.
                    matches = re.findall(
                        r"(?:^|\n)(Article\s+(?:28|44|45|46)\b.*?)(?=\nArticle\s+\d+\b|\Z)",
                        downloaded,
                        flags=re.S,
                    )
                    downloaded = "\n\n".join(matches)
                    if not downloaded or any(f"Article {section}" not in downloaded for section in (28, 44, 45, 46)):
                        raise ValueError("could not isolate all requested GDPR articles from EUR-Lex text")
                if "Page Not Found" in downloaded[:300] or "The requested URL was not found" in downloaded[:500]:
                    raise ValueError("source returned a not-found page")
                entry["url"] = source_url
                if "law.cornell.edu" in (source_url or ""):
                    entry["source"] = "Cornell Legal Information Institute"
                entry["text"], entry["retrieved_at"] = downloaded, retrieved_at
                print(f"Fetched {key}")
                break
            except Exception as exc:
                failure = exc
        if entry["text"] is None:
            entry["retrieved_at"] = None
            print(f"WARNING: could not fetch {key} from {entry['url']}: {failure}", file=sys.stderr)
    OUTPUT.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(entries)} statute entries to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
