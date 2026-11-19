"""Public pitch/docs page API with scheduled visibility and protected editing."""
from __future__ import annotations

from datetime import datetime
import hmac
import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import settings
from app.services.docs_store import DocsStore, is_in_window


router = APIRouter(prefix="/docs", tags=["project documentation"])
store = DocsStore(settings.docs_db_path)
COOKIE_NAME = "legalcopilot_docs_admin"


class TeamMember(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    role: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    image_url: str = Field(default="", max_length=1000)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid contact email")
        return value

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: str):
        if value and not (value.startswith("https://") or (value.startswith("/") and not value.startswith("//"))):
            raise ValueError("Profile images must use HTTPS or a same-site path")
        return value


class DocsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,60}$")
    title: str = Field(min_length=1, max_length=120)
    group: Literal["pitch", "product", "engineering"]
    content: str = Field(max_length=30000)


class DocsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    team_name: str = Field(default="", max_length=120)
    tagline: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=3000)
    team_members: list[TeamMember] = Field(default_factory=list, max_length=30)
    sections: list[DocsSection] = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def unique_section_ids(self):
        ids = [item.id for item in self.sections]
        if len(ids) != len(set(ids)):
            raise ValueError("Section IDs must be unique")
        return self


class AccessUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    start_at: datetime
    end_at: datetime
    repeat_yearly: bool = False
    timezone: Literal["Asia/Dhaka"] = "Asia/Dhaka"

    @field_validator("start_at", "end_at")
    @classmethod
    def require_timezone(cls, value: datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Schedule dates must include a timezone")
        return value

    @model_validator(mode="after")
    def valid_window(self):
        if self.end_at <= self.start_at:
            raise ValueError("End date must be after start date")
        return self


class AdminLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=512)


def _admin_configured() -> str:
    token = settings.docs_admin_token.strip()
    if not token:
        raise HTTPException(503, "Documentation admin is disabled. Set DOCS_ADMIN_TOKEN on the backend.")
    return token


def _require_admin(request: Request) -> None:
    expected = _admin_configured()
    actual = request.cookies.get(COOKIE_NAME, "")
    if not actual or not hmac.compare_digest(actual, expected):
        raise HTTPException(401, "Admin login required.")


def _public_allowed(state: dict) -> bool:
    access = state["access"]
    return bool(access.get("enabled")) and is_in_window(access)


async def _live_snapshot() -> dict:
    provider = settings.llm_provider
    configured = bool(settings.active_api_key) if provider == "gemini" else True
    runtime_model = settings.active_model
    if provider == "lmstudio":
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{settings.lm_studio_base_url.rstrip('/')}/models")
                response.raise_for_status()
                loaded = response.json().get("data", [])
            configured = bool(loaded)
            if configured and (not settings.lm_studio_model.strip() or settings.lm_studio_model == "auto"):
                runtime_model = str(loaded[0].get("id") or "auto")
        except Exception:
            configured = False
    workflow_nodes = [
        "ingest", "segment", "detect_jurisdiction", "checklist_scan",
        "cross_clause_scan", "research", "build_bank", "draft_memo", "verify", "finalize",
    ]
    return {
        "checked_at": datetime.now().astimezone().isoformat(),
        "provider": provider,
        "model": runtime_model,
        "provider_configured": configured,
        "workflow_nodes": workflow_nodes,
        "features": {
            "upload_formats": ["PDF", "DOCX", "TXT", "PNG", "JPEG", "TIFF"],
            "max_upload_bytes": settings.max_upload_bytes,
            "session_ttl_seconds": settings.session_ttl_seconds,
            "session_store": "process memory",
            "statute_corpus": True,
            "bm25_retrieval": True,
            "voyage_embeddings": bool(settings.voyage_api_key),
            "cohere_reranking": bool(settings.cohere_api_key),
            "courtlistener_token_configured": bool(settings.courtlistener_token or settings.courtlistener_api_token),
            "analytics_collection": False,
        },
        "api_endpoints": [
            {"method": "GET", "path": "/docs", "purpose": "Scheduled public pitch and technical documentation"},
            {"method": "GET", "path": "/docs/export.md", "purpose": "Scheduled Markdown export"},
            {"method": "POST", "path": "/docs/admin/session", "purpose": "Exchange admin token for a protected session cookie"},
            {"method": "GET", "path": "/docs/admin", "purpose": "Read admin draft, schedule, and version history"},
            {"method": "PUT", "path": "/docs/admin/draft", "purpose": "Save a documentation draft"},
            {"method": "POST", "path": "/docs/admin/publish", "purpose": "Publish the saved draft"},
            {"method": "PUT", "path": "/docs/admin/access", "purpose": "Change public visibility and schedule"},
            {"method": "GET", "path": "/health", "purpose": "API and model-provider configuration"},
            {"method": "POST", "path": "/sessions", "purpose": "Create a temporary document session"},
            {"method": "POST", "path": "/sessions/{id}/analyze", "purpose": "Run analysis and stream progress"},
            {"method": "GET", "path": "/sessions/{id}/memo", "purpose": "Read the completed assessment"},
            {"method": "DELETE", "path": "/sessions/{id}", "purpose": "Purge temporary session state"},
            {"method": "POST", "path": "/verify", "purpose": "Citation identity probe; not substantive legal verification"},
        ],
    }


@router.get("")
async def public_docs():
    state = store.state()
    if not state.get("published") or not _public_allowed(state):
        raise HTTPException(404, "Documentation is not available.")
    return {"document": state["published"], "live": await _live_snapshot(), "published_at": state["published_at"]}


@router.get("/export.md")
def export_markdown():
    state = store.state()
    if not state.get("published") or not _public_allowed(state):
        raise HTTPException(404, "Documentation is not available.")
    document = state["published"]
    output = [f"# {document['title']}", f"\n> {document['tagline']}\n", document["summary"]]
    for section in document["sections"]:
        output.extend([f"\n## {section['title']}\n", section["content"]])
    if document.get("team_members"):
        output.append("\n## Team\n")
        for member in document["team_members"]:
            output.append(f"- **{member['name']}** — {member['role']} ({member['email']})")
    return Response("\n".join(output), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="legal-copilot-docs.md"', "Cache-Control": "no-store"})


@router.post("/admin/session")
def admin_login(body: AdminLogin, request: Request, response: Response):
    expected = _admin_configured()
    if not hmac.compare_digest(body.token, expected):
        raise HTTPException(401, "Invalid admin token.")
    secure_cookie = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
    response.set_cookie(
        COOKIE_NAME, expected, httponly=True, secure=secure_cookie,
        samesite="strict", max_age=8 * 60 * 60, path="/",
    )
    return {"authenticated": True}


@router.delete("/admin/session")
def admin_logout(request: Request, response: Response):
    secure_cookie = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, secure=secure_cookie, samesite="strict")
    return {"authenticated": False}


@router.get("/admin")
def admin_state(request: Request):
    _require_admin(request)
    return store.state()


@router.put("/admin/draft")
def save_draft(body: DocsDocument, request: Request):
    _require_admin(request)
    return store.save_draft(body.model_dump(mode="json"))


@router.post("/admin/publish")
def publish_draft(request: Request):
    _require_admin(request)
    return store.publish()


@router.put("/admin/access")
def update_access(body: AccessUpdate, request: Request):
    _require_admin(request)
    return store.update_access(body.model_dump(mode="json"))
