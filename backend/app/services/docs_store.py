"""Persistent pitch and documentation content, schedules, and version history."""
from __future__ import annotations

from datetime import datetime
import json
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo


BD_TZ = ZoneInfo("Asia/Dhaka")


def default_document() -> dict[str, Any]:
    sections = [
        ("problem", "Problem", "pitch", "Small businesses and startup teams often review commercial agreements without in-house counsel. Important obligations can be buried in clauses or emerge from interactions between terms. Legal Copilot helps organize an initial review; it does not replace qualified counsel."),
        ("solution", "Solution", "pitch", "Upload an agreement and receive a preliminary, quote-linked list of potential contract issues, clause references, and suggested follow-up actions. Findings are conditional and grounded against the uploaded text."),
        ("why-now", "Why now", "pitch", "Teams increasingly handle digital contracts and need faster intake before professional review. Local inference options can also support teams that prefer to keep model processing on their own machine."),
        ("demo", "Product demo", "pitch", "The current application accepts PDF, DOCX, TXT, PNG, JPEG, and TIFF uploads. It extracts text, identifies clauses, analyzes risk, validates quoted evidence, and presents a preliminary assessment. OCR and model availability affect results."),
        ("market", "Market opportunity", "pitch", "Initial customer hypotheses are Bangladesh startups, SMEs, procurement teams, and small legal teams that review recurring commercial agreements. Demand, willingness to pay, and market size require customer interviews and pilot validation."),
        ("business-model", "Business model", "pitch", "Models to test include per-document triage, a team subscription with usage limits, and counsel-assisted intake tooling. No pricing or commercial validation is claimed yet."),
        ("traction", "Traction", "pitch", "The project is a working prototype. No customer traction, deployment usage, or live model quality benchmark is claimed in this documentation."),
        ("competition", "Competition", "pitch", "Alternatives include manual counsel review, contract lifecycle management systems, and general-purpose AI assistants. Legal Copilot focuses on clause-linked evidence and explicit coverage limitations."),
        ("advantage", "Unique advantage", "pitch", "The prototype checks that displayed contract quotations exist in the uploaded text and surfaces omissions and evidence gaps. This improves traceability but does not establish that a risk interpretation is legally correct."),
        ("go-to-market", "Go-to-market", "pitch", "Start with interviews and a small, counsel-reviewed pilot using synthetic or authorized, redacted agreements. Expand only after measuring usefulness, privacy requirements, and error rates."),
        ("team", "Team", "pitch", "Team members and roles are maintained by an administrator. No names, roles, emails, or profile images are prefilled; add only approved showcase details."),
        ("vision", "Vision", "pitch", "Build a practical, evidence-linked first step for contract review, with jurisdiction-aware sources and Bangla support developed and validated with local legal reviewers."),
        ("overview", "Product overview", "product", "Legal Copilot is a preliminary contract risk-triage assistant. It extracts contract text, segments clauses, identifies jurisdiction clues, asks a configured language model for potential issues, then filters findings through deterministic clause and quote checks."),
        ("features", "Feature matrix", "product", "Current: PDF/DOCX/TXT/image ingestion; clause segmentation; jurisdiction clue detection; quote-grounded risk findings; warnings; text and print/PDF export; session purge. Planned: verified Bangladesh legal-source coverage, Bangla evaluation, reviewer workflows, and measured pilots."),
        ("architecture", "Architecture", "engineering", "Browser UI → Next.js frontend → FastAPI session API → in-memory session store → document parser and clause segmenter → configured LLM adapter → Pydantic validation and exact-quote checks → browser report. A separate full research workflow includes BM25 legal-source retrieval, optional Voyage/Qdrant vector search, optional Cohere reranking, authority-bank construction, and support verification; it is not assumed active in every UI path."),
        ("data-flow", "Data flow", "engineering", "Upload → volatile session → local parsing/OCR where available → clause segmentation → jurisdiction clues → risk prompt → structured model response → clause-ID and quote validation → assessment and warnings → purge or TTL expiry."),
        ("stack", "Technology stack", "engineering", "Frontend: Next.js, React, TypeScript, Tailwind CSS. Backend: Python, FastAPI, Pydantic, LangGraph. Parsing: PyMuPDF, python-docx, Pillow, optional Tesseract. The separate research path uses rank-bm25, in-memory Qdrant, and optional Voyage/Cohere integrations."),
        ("api", "API documentation", "engineering", "GET /health reports API and model configuration. POST /sessions uploads a document. POST /sessions/{id}/analyze streams progress and a result. GET /sessions/{id}/memo reads a completed assessment. DELETE /sessions/{id} purges a session. Additional verification and export routes exist; consult the OpenAPI page at /openapi.json for the running backend."),
        ("data-layer", "Data layer and privacy", "engineering", "Uploaded bytes and session results are held in process memory and expire by TTL or explicit purge. The bundled statute corpus is stored as JSON for the separate research workflow. Configured model providers and optional retrieval services may receive the text required for their function; provider and hosting retention are outside the application-memory guarantee."),
        ("ai-layer", "AI layer and retrieval", "engineering", "The active review path depends on the configured provider and route. Structured output is validated locally; findings require valid clause references and matching contract quotations. The separate research path can retrieve exact legal-source chunks using BM25, optionally add Voyage legal embeddings in request-scoped Qdrant, and optionally rerank with Cohere. This is not GraphRAG or a persistent vector index."),
        ("roadmap", "Product roadmap", "engineering", "Near term: stabilize supported document formats and provider errors. Mid term: build a counsel-reviewed evaluation set, verify jurisdiction-specific sources, and test Bangla contracts. Longer term: add controlled team access, durable reviewed session architecture, usage analytics, and scalable deployments."),
        ("performance", "Performance and scalability", "engineering", "The API uses process-local sessions and should run with one worker until session coordination is redesigned. File size and session TTL are configurable. Model latency and quotas vary by provider. Long-document handling uses bounded input selection where configured; no production load benchmark is claimed."),
        ("security", "Security", "engineering", "Use HTTPS, protect provider credentials, restrict CORS, redact session IDs from logs, and upload only documents permitted by provider and hosting terms. Sessions can be purged and expire by TTL. This prototype has no general user account or contract-level authorization system."),
        ("analytics", "Analytics and KPIs", "engineering", "The application does not currently collect product usage analytics. Proposed pilot measures: human-reviewed risk precision and recall, quote correctness, coverage disclosure, time to prepare for counsel review, provider completion rate, latency, and cost per review. Targets must be measured before being reported as results."),
        ("contributors", "Team and contributors", "engineering", "The showcase team list is administrator-managed. Add only contributors who have approved publishing their profile and contact details."),
        ("changelog", "Changelog", "engineering", "Initial live documentation draft. Admin publishing creates an append-only documentation version record."),
    ]
    return {
        "title": "Legal Copilot",
        "team_name": "",
        "tagline": "Evidence-linked contract review, prepared for counsel.",
        "summary": "A working prototype that helps teams identify potential contract issues, trace them to source wording, and prepare focused questions for qualified counsel.",
        "team_members": [],
        "sections": [
            {"id": key, "title": title, "group": group, "content": content}
            for key, title, group, content in sections
        ],
    }


def default_access() -> dict[str, Any]:
    return {
        "enabled": True,
        "start_at": "2027-06-10T00:00:00+06:00",
        "end_at": "2027-06-14T23:59:00+06:00",
        "repeat_yearly": True,
        "timezone": "Asia/Dhaka",
    }


class DocsStore:
    def __init__(self, path: str = ""):
        self.path = Path(path) if path else Path(__file__).resolve().parents[2] / "data" / "docs.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""CREATE TABLE IF NOT EXISTS docs_state (
                id INTEGER PRIMARY KEY CHECK (id = 1), draft_json TEXT NOT NULL,
                published_json TEXT NOT NULL, access_json TEXT NOT NULL,
                updated_at TEXT NOT NULL, published_at TEXT NOT NULL
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS docs_versions (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, action TEXT NOT NULL,
                document_json TEXT NOT NULL
            )""")
            existing = connection.execute("SELECT id FROM docs_state WHERE id=1").fetchone()
            if not existing:
                document = default_document()
                encoded = json.dumps(document, ensure_ascii=False)
                now = datetime.now(BD_TZ).isoformat()
                connection.execute(
                    "INSERT INTO docs_state VALUES (1, ?, ?, ?, ?, ?)",
                    (encoded, encoded, json.dumps(default_access()), now, now),
                )
                connection.execute(
                    "INSERT INTO docs_versions VALUES (?, ?, ?, ?)",
                    (str(uuid4()), now, "initial-publish", encoded),
                )

    def state(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM docs_state WHERE id=1").fetchone()
            versions = connection.execute(
                "SELECT id, created_at, action FROM docs_versions ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
        return {
            "draft": json.loads(row["draft_json"]),
            "published": json.loads(row["published_json"]),
            "access": json.loads(row["access_json"]),
            "updated_at": row["updated_at"],
            "published_at": row["published_at"],
            "versions": [dict(item) for item in versions],
        }

    def save_draft(self, document: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(document, ensure_ascii=False)
        now = datetime.now(BD_TZ).isoformat()
        with self._connect() as connection:
            connection.execute("UPDATE docs_state SET draft_json=?, updated_at=? WHERE id=1", (encoded, now))
            connection.execute("INSERT INTO docs_versions VALUES (?, ?, ?, ?)", (str(uuid4()), now, "draft-saved", encoded))
        return self.state()

    def publish(self) -> dict[str, Any]:
        now = datetime.now(BD_TZ).isoformat()
        with self._connect() as connection:
            row = connection.execute("SELECT draft_json FROM docs_state WHERE id=1").fetchone()
            connection.execute("UPDATE docs_state SET published_json=?, published_at=?, updated_at=? WHERE id=1", (row["draft_json"], now, now))
            connection.execute("INSERT INTO docs_versions VALUES (?, ?, ?, ?)", (str(uuid4()), now, "published", row["draft_json"]))
        return self.state()

    def update_access(self, access: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(BD_TZ).isoformat()
        with self._connect() as connection:
            connection.execute("UPDATE docs_state SET access_json=?, updated_at=? WHERE id=1", (json.dumps(access), now))
            connection.execute("INSERT INTO docs_versions VALUES (?, ?, ?, ?)", (str(uuid4()), now, "access-updated", "{}"))
        return self.state()


def is_in_window(access: dict[str, Any], now: datetime | None = None) -> bool:
    current = (now or datetime.now(BD_TZ)).astimezone(BD_TZ)
    try:
        start = datetime.fromisoformat(access["start_at"]).astimezone(BD_TZ)
        end = datetime.fromisoformat(access["end_at"]).astimezone(BD_TZ)
    except (KeyError, TypeError, ValueError):
        return False
    if end <= start:
        return False
    if access.get("repeat_yearly"):
        try:
            start = start.replace(year=current.year)
            end = end.replace(year=current.year)
        except ValueError:  # Handles a Feb. 29 schedule safely.
            return False
    return start <= current <= end
