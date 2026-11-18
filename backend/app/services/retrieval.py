import asyncio, re
from rank_bm25 import BM25Okapi
from qdrant_client import QdrantClient, models
from app.config import settings


MIN_BM25_SCORE = 2.0
MIN_DISTINCT_TERM_MATCHES = 2
MAX_CHUNKS_PER_ENTRY = 1
_TAG_BOOST = 1.5
_JURISDICTION_BOOST = 0.25
_NARROW_TOPICS = {"data_processing", "data_transfer", "security_breach", "data_practices"}
_TOPIC_TERMS = {
    "data_protection": re.compile(r"\b(?:data|privacy|personal information|personal data|processor|controller|security|breach|consent|transfer)\b", re.I),
    "data_processing": re.compile(r"\b(?:processor|processing|controller|processing activities)\b", re.I),
    "data_transfer": re.compile(r"\b(?:transfer|cross[- ]border|third[- ]country|international transfer)\b", re.I),
    "security_breach": re.compile(r"\b(?:security|breach|incident|notification)\b", re.I),
    "data_practices": re.compile(r"\b(?:consent|collection|collects?|personal information|consumer data|data definition|data subject rights)\b", re.I),
    "employment": re.compile(r"\b(?:employment|employee|employer|wage|hour|overtime|payroll|worker)\b", re.I),
    "ip_trade_secret": re.compile(r"\b(?:intellectual property|copyright|patent|trademark|trade secret|proprietary information|invention)\b", re.I),
    "antitrust_competition": re.compile(r"\b(?:antitrust|competition|competitor|restraint of trade|non[- ]compete|non[- ]solicit|unfair method)\b", re.I),
    "consumer_protection": re.compile(r"\b(?:consumer|deceptive|consumer protection|unfair practice)\b", re.I),
    "general_contract": re.compile(r"\b(?:contract|agreement|liability|indemnif(?:y|ication)|renewal|termination|governing law|assignment|notice|cap|carve[- ]out)\b", re.I),
}


def split_entry_chunks(entry: dict) -> list[dict]:
    """Split stored source into paragraph/subsection slices without rewriting text."""
    text = str(entry.get("text") or "")
    if not text.strip():
        return []
    key = str(entry.get("key") or "")
    marker = re.compile(
        r"(?m)^[ \t\u00a0]*(\([a-z0-9]+\)|\d+\.)"
        r"(?=[ \t\u00a0]*(?:\r?\n[ \t\u00a0]*)?\S)", re.I,
    )
    matches = list(marker.finditer(text))
    if matches:
        chunks = []
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            chunk_text = text[start:end]
            locator = match.group(1).strip()
            chunks.append({**entry, "text": chunk_text, "chunk_locator": locator})
        return chunks
    # One unnumbered paragraph/article is still an exact source slice.
    article = re.search(r"\bART\.\s*(\d+)\b", key, re.I)
    locator = f"Art. {article.group(1)}" if article else "whole section"
    return [{**entry, "text": text, "chunk_locator": locator}]


def _query_topics(query: str) -> set[str]:
    return {tag for tag, pattern in _TOPIC_TERMS.items() if pattern.search(query)}


def infer_topic_tags(text: str) -> set[str]:
    return _query_topics(text)


def _query_jurisdictions(query: str) -> set[str]:
    found = set()
    if re.search(r"\b(?:EU|EEA|European Union|GDPR)\b", query, re.I):
        found.add("EU")
    if re.search(r"\b(?:California|Cal\.|CCPA|CPRA)\b", query, re.I):
        found.add("California")
    if re.search(r"\b(?:United States|U\.S\.|US law|Delaware|New York|federal law)\b", query, re.I):
        found.add("US")
    return found


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


class BM25EntryIndex:
    """In-memory BM25 index over exact paragraph/subsection source slices."""

    def __init__(self, entries: list[dict]):
        self.entries = [chunk for entry in entries for chunk in split_entry_chunks(entry)]
        self.documents = [" ".join(str(entry.get(field) or "") for field in ("key", "title", "chunk_locator", "text")) for entry in self.entries]
        self._index = BM25Okapi([_tokens(document) for document in self.documents]) if entries else None

    def search(self, query: str, *, top_k: int = 4, min_score: float = MIN_BM25_SCORE,
               min_distinct_matches: int = MIN_DISTINCT_TERM_MATCHES,
               topic_tags: set[str] | None = None, context_text: str = "") -> list[dict]:
        if not self._index or not self.entries:
            return []
        query_terms = set(_tokens(query))
        topics = _query_topics(query) if topic_tags is None else topic_tags
        narrow_topics = topics.intersection(_NARROW_TOPICS)
        jurisdictions = _query_jurisdictions(context_text or query)
        context_topics = _query_topics(context_text) if context_text else set()
        scores = self._index.get_scores(sorted(query_terms))
        ranked = sorted(range(len(scores)), key=lambda i: (-float(scores[i]), str(self.entries[i].get("key", ""))))
        per_parent: dict[str, list[dict]] = {}
        for index in ranked:
            entry = self.entries[index]
            tags = set(entry.get("topic_tags") or [])
            if narrow_topics and tags and not narrow_topics.intersection(tags):
                continue
            if topics and tags and not topics.intersection(tags):
                continue
            text_terms = set(_tokens(str(entry.get("text") or "")))
            distinct_matches = len(query_terms.intersection(text_terms))
            raw_score = float(scores[index])
            if raw_score < min_score or distinct_matches < min_distinct_matches:
                continue
            score = raw_score
            if topics.intersection(tags):
                score += _TAG_BOOST
            if context_topics.intersection(tags):
                score += 0.25
            entry_jurisdictions = set(entry.get("jurisdictions") or [])
            if jurisdictions.intersection(entry_jurisdictions):
                score += _JURISDICTION_BOOST
            key = str(entry.get("key", ""))
            hit = {"entry": entry, "score": score, "bm25_score": raw_score, "distinct_term_matches": distinct_matches}
            per_parent.setdefault(key, []).append(hit)
        capped = [hit for hits in per_parent.values() for hit in sorted(hits, key=lambda row: -row["score"])[:MAX_CHUNKS_PER_ENTRY]]
        return sorted(capped, key=lambda hit: (-hit["score"], hit["entry"].get("key", "")))[:top_k]


def _vector_rank(query: str, chunks: list[str]) -> list[str]:
    """Build a request-scoped in-memory Qdrant index from Voyage legal embeddings."""
    import voyageai
    client = voyageai.Client(api_key=settings.voyage_api_key)
    docs = client.embed(chunks, model="voyage-law-2", input_type="document").embeddings
    query_vector = client.embed([query], model="voyage-law-2", input_type="query").embeddings[0]
    qdrant = QdrantClient(":memory:")
    name = "legal_chunks"
    qdrant.create_collection(name, vectors_config=models.VectorParams(size=len(query_vector), distance=models.Distance.COSINE))
    qdrant.upsert(name, points=[models.PointStruct(id=i, vector=vector, payload={"text": chunks[i]}) for i, vector in enumerate(docs)])
    hits = qdrant.query_points(name, query=query_vector, limit=min(16, len(chunks))).points
    results = [hit.payload["text"] for hit in hits]
    qdrant.close()
    return results


def _rerank(query: str, candidates: list[str]) -> list[str]:
    import cohere
    client = cohere.ClientV2(api_key=settings.cohere_api_key)
    response = client.rerank(model="rerank-v3.5", query=query, documents=candidates, top_n=min(8, len(candidates)))
    return [candidates[item.index] for item in response.results]


async def embed_and_rerank(query: str, chunks: list[str]) -> list[str]:
    """Hybrid lexical/vector candidate search and optional Cohere reranking.

    Every Qdrant collection is in-memory and scoped to one analysis call. BM25 remains
    the offline fallback if external embedding/reranking providers are not configured.
    """
    if not chunks:
        return []
    lexical_order = []
    bm25 = BM25Okapi([_tokens(c) for c in chunks])
    scores = bm25.get_scores(_tokens(query))
    lexical_order = [chunks[i] for i in sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)[:16]]
    candidates = lexical_order
    if settings.voyage_api_key:
        try:
            vectors = await asyncio.to_thread(_vector_rank, query, chunks)
            candidates = list(dict.fromkeys(lexical_order + vectors))
        except Exception:
            pass
    if settings.cohere_api_key and candidates:
        try:
            return await asyncio.to_thread(_rerank, query, candidates)
        except Exception:
            pass
    return candidates[:8] or chunks[:8]
