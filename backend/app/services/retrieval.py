import asyncio, re
from rank_bm25 import BM25Okapi
from qdrant_client import QdrantClient, models
from app.config import settings


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


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
