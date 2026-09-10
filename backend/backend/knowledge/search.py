"""Semantic search over chunk embeddings (US-227, T-S2-6).

pgvector HNSW with cosine distance (migration 0013). Only chunks of the
caller's organization, current asset versions and non-deleted assets are
searchable (ADR-024 + US-241).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.knowledge.embeddings import embed_one
from backend.models import KnowledgeAsset, KnowledgeChunk


async def semantic_search(
    session: AsyncSession, organization_id, query: str, top_k: int | None = None
) -> dict:
    """Embed the query, rank chunks by cosine distance, return top-k hits."""
    settings = get_settings()
    limit = min(top_k or settings.search_default_top_k, settings.search_max_top_k)
    if limit < 1:
        raise ApiError(400, "VALIDATION_ERROR", "top_k must be positive.")
    if not query.strip():
        raise ApiError(400, "EMPTY_QUERY", "The search query is empty.")

    vector = embed_one(query)
    rows = (
        (
            await session.execute(
                select(
                    KnowledgeChunk,
                    KnowledgeAsset.name,
                    KnowledgeChunk.embedding.cosine_distance(vector),
                )
                .join(KnowledgeAsset, KnowledgeChunk.asset_id == KnowledgeAsset.id)
                .where(
                    KnowledgeChunk.organization_id == organization_id,
                    KnowledgeChunk.asset_version == KnowledgeAsset.version,
                    KnowledgeChunk.embedding.is_not(None),
                    KnowledgeAsset.deleted_at.is_(None),
                )
                .order_by(KnowledgeChunk.embedding.cosine_distance(vector))
                .limit(limit)
            )
        )
        .all()
    )
    hits = [
        {
            "asset_id": chunk.asset_id,
            "asset_name": asset_name,
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "score": round(1.0 - float(distance), 4),
        }
        for chunk, asset_name, distance in rows
    ]
    await record_audit(
        session,
        "knowledge.search",
        organization_id=organization_id,
        detail={"query_chars": len(query), "top_k": limit, "hits": len(hits)},
    )
    return {"query_chars": len(query), "results": hits}
