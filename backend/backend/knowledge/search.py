"""Semantic search over chunk embeddings (US-227, T-S2-6).

pgvector HNSW with cosine distance (migration 0013). Only chunks of the
caller's organization, current asset versions and non-deleted assets are
searchable (ADR-024 + US-241).

Also bounded by folder ownership. This is the highest-impact read path in the
product: whatever it returns becomes the context of an AI answer, so an
organization-only filter did not merely expose a colleague's file in a list -
it fed that file into someone else's generated answer, where the leak looks like
the system knowing something it should not.
"""


from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api_errors import ApiError
from backend.audit import record_audit
from backend.config import get_settings
from backend.knowledge.assets import is_org_admin, visible_to
from backend.knowledge.embeddings import embed_one
from backend.knowledge.rerank import RERANK_CANDIDATES, rerank
from backend.models import KnowledgeAsset, KnowledgeChunk

# Relevance floor (P2-9, staging audit 2026-09-14).
#
# Measured on the real corpus: a relevant query scores 0.72-0.76, gibberish
# ("xyzzy plugh frobnicate qqqqq") scores 0.31-0.37. The API nevertheless
# returned a full page of top_k hits for the gibberish, so a user asking about
# something absent from the knowledge base saw five confident-looking citations.
#
# 0.5 sits roughly in the middle of the measured gap: above every gibberish
# score seen (0.37) and below every relevant one (0.72), with margin on both
# sides. It is deliberately a value in the gap rather than a percentile of the
# returned set, because a percentile would always keep the best N whatever their
# absolute quality - which is the bug.
MIN_RELEVANCE_SCORE = 0.5

# Even a relevant query can carry a weak tail: the floor alone would let one
# 0.51 outlier through for a query that is really about nothing. A minimum count
# makes "found nothing" the answer when only one marginal chunk clears the bar.
# Both rules must hold; either alone reintroduces the failure from one side.
MIN_RELEVANCE_HITS = 1


async def semantic_search(
    session: AsyncSession, organization_id, query: str, top_k: int | None = None, user_id=None
) -> dict:
    """Embed the query, rank chunks by cosine distance, return top-k hits.

    Hits below MIN_RELEVANCE_SCORE are dropped, so an empty "results" list is a
    real answer ("this organization's knowledge does not cover the question")
    rather than a ranking artefact. The callers - the search API and the
    execution cycle - branch on len(hits), and the citation instruction is only
    attached when there are hits.
    """
    settings = get_settings()
    limit = min(top_k or settings.search_default_top_k, settings.search_max_top_k)
    if limit < 1:
        raise ApiError(400, "VALIDATION_ERROR", "top_k must be positive.")
    if not query.strip():
        raise ApiError(400, "EMPTY_QUERY", "The search query is empty.")
    # The organization Owner reads the whole organization's knowledge (PO
    # access model: collected org-wide, read by level).
    is_admin = await is_org_admin(session, organization_id, user_id)
    # Close the read transaction before inference. The transaction this opens
    # would otherwise stay open - "idle in transaction" - for the whole embed,
    # which can wait up to the inference queue timeout, and a held transaction
    # blocks every writer that needs the same rows.
    #
    # Measured on staging at 20 users: a search session sat idle in transaction
    # for 3 m 16 s after a knowledge_chunks SELECT, blocking an
    # "UPDATE hiveos.sessions SET expires_at" - and because every authenticated
    # request refreshes its session row, that single blocked update stalled the
    # whole API, including endpoints that do no inference at all.
    await session.commit()

    # Embedding is async now: the local provider offloads to a thread, the
    # remote one awaits HTTP.
    vector = await embed_one(query)
    candidates_pool = getattr(settings, "rerank_candidates", RERANK_CANDIDATES)
    pool = max(limit, candidates_pool if settings.rerank_enabled else limit)
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
                    # Same rule as the file list and the download path: the
                    # caller's own files plus the organization's shared ones.
                    # imported here rather than duplicated, so all four read
                    # paths cannot drift apart again.
                    visible_to(user_id, is_admin),
                )
                .order_by(KnowledgeChunk.embedding.cosine_distance(vector))
                .limit(pool)
            )
        )
        .all()
    )
    # Copy the columns out and release the read transaction BEFORE reranking.
    # The same reason as above: rerank runs the cross-encoder for seconds per
    # call, and holding the transaction across it leaves a session idle in
    # transaction for that whole window. Plain values are copied rather than the
    # ORM rows so nothing here depends on the session staying open.
    recalled = [
        (
            row[0].asset_id,
            row[1],
            row[0].chunk_index,
            row[0].content,
            round(1.0 - float(row[2]), 4),
        )
        for row in rows
    ]
    await session.commit()

    # Recall stage done; order the candidates by relevance before trimming to
    # top_k. Falls back to the vector order when reranking is unavailable.
    order = await rerank(query, [item[3] for item in recalled], limit) if recalled else []
    candidates = [
        {
            "asset_id": recalled[index][0],
            "asset_name": recalled[index][1],
            "chunk_index": recalled[index][2],
            "content": recalled[index][3],
            "score": recalled[index][4],
        }
        for index in order
    ]
    # Relevance floor + minimum hits (P2-9): see the constants above. Filtering
    # AFTER reranking is deliberate - the reranker orders candidates but does not
    # change the cosine score, and the floors are calibrated on that score.
    hits = [hit for hit in candidates if hit["score"] >= MIN_RELEVANCE_SCORE]
    if len(hits) < MIN_RELEVANCE_HITS:
        hits = []
    await record_audit(
        session,
        "knowledge.search",
        organization_id=organization_id,
        detail={
            "query_chars": len(query),
            "top_k": limit,
            "hits": len(hits),
            "candidates": len(candidates),
            "floor": MIN_RELEVANCE_SCORE,
        },
    )
    return {"query_chars": len(query), "results": hits}
