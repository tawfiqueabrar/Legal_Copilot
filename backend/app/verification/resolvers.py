"""Network resolvers. All HTTP is injectable; provider failures never verify authority."""
import json
from pathlib import Path
from typing import Any, Protocol
import httpx
from app.config import settings
from .extract import CitationCandidate, normalize_citation
from .models import Authority, Citation


class Resolver(Protocol):
    async def resolve(self, citation: Citation) -> Authority | None: ...


class CourtListenerResolver:
    API = "https://www.courtlistener.com/api/rest/v4"

    def __init__(self, token: str | None = None, http: Any = None):
        self.token = token if token is not None else (settings.courtlistener_token or settings.courtlistener_api_token)
        self.http = http or httpx.AsyncClient(timeout=20, follow_redirects=True)
        self._owns_client = http is None

    async def close(self):
        if self._owns_client:
            await self.http.aclose()

    async def _send(self, method: str, url: str, **kwargs):
        if callable(self.http) and not hasattr(self.http, method.lower()):
            return await self.http(method, url, **kwargs)
        return await getattr(self.http, method.lower())(url, **kwargs)

    async def resolve(self, citation: Citation) -> Authority | None:
        try:
            headers = {"Authorization": f"Token {self.token}"} if self.token else {}
            response = await self._send("post", f"{self.API}/citation-lookup/", data={"text": citation.raw}, headers=headers)
            response.raise_for_status()
            items = response.json()
            if not isinstance(items, list):
                return None
            for item in items:
                if item.get("status") != 200:
                    continue
                normalized = item.get("normalized_citations") or [item.get("citation", "")]
                if not any(normalize_citation(value, citation.kind) == citation.normalized_key for value in normalized):
                    continue
                clusters = item.get("clusters") or []
                cluster = clusters[0] if clusters else {}
                title = cluster.get("case_name") or citation.raw
                url = cluster.get("absolute_url") or cluster.get("url") or "https://www.courtlistener.com"
                if url.startswith("/"):
                    url = "https://www.courtlistener.com" + url
                opinion_text = await self._opinion_text(cluster, headers)
                return Authority(id="A1", key=citation.normalized_key, kind=citation.kind, title=title,
                                 source="courtlistener", url=url, text=opinion_text,
                                 status="resolved" if opinion_text else "existence-only")
            return None
        except Exception:
            return None

    async def _opinion_text(self, cluster: dict, headers: dict) -> str | None:
        sub_opinions = cluster.get("sub_opinions") or cluster.get("opinions") or []
        for opinion in sub_opinions[:3]:
            url = opinion if isinstance(opinion, str) else opinion.get("resource_uri") or opinion.get("url")
            if not url:
                continue
            if url.startswith("/"):
                url = "https://www.courtlistener.com" + url
            try:
                response = await self._send("get", url, headers=headers)
                response.raise_for_status()
                payload = response.json()
                text = payload.get("plain_text") or payload.get("html_with_citations") or payload.get("html")
                if text:
                    return str(text)
            except Exception:
                continue
        return None


class StaticCorpusResolver:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else Path(__file__).resolve().parents[2] / "data" / "statutes.json"

    def _entries(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}

    async def resolve(self, citation: Citation) -> Authority | None:
        entry = self._entries().get(citation.normalized_key)
        if not entry:
            return None
        text = entry.get("text") or None
        retrieved = entry.get("retrieved_at") or None
        resolved = bool(text and retrieved and entry.get("url"))
        return Authority(id="A1", key=citation.normalized_key, kind=citation.kind,
                         title=entry.get("title") or citation.raw, source=entry.get("source", "static-corpus"),
                         url=entry.get("url", ""), text=text, retrieved_at=retrieved,
                         status="resolved" if resolved else "existence-only")


class CompositeResolver:
    def __init__(self, resolvers: list[Resolver]):
        self.resolvers = resolvers

    async def resolve(self, citation: Citation) -> Authority | None:
        for resolver in self.resolvers:
            try:
                authority = await resolver.resolve(citation)
                if authority:
                    return authority
            except Exception:
                continue
        return None


async def build_bank(citations: list[Citation | CitationCandidate], resolver: Resolver):
    from .bank import AuthorityBank
    citations = [item if isinstance(item, Citation) else Citation(kind=item.kind, raw=item.raw, normalized_key=item.normalized_key) for item in citations]
    resolved = []
    for citation in sorted(citations, key=lambda item: item.normalized_key):
        try:
            authority = await resolver.resolve(citation)
        except Exception:
            authority = None
        if authority:
            resolved.append(authority)
    return AuthorityBank(resolved)
