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


from sqlalchemy import func, select
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

# Below the bottom of the cosine range: "no floor applies". Used for an
# embedding provider whose score carries no semantics (see relevance_floor).
NO_SEMANTIC_FLOOR = -1.0


def relevance_floor(provider: str | None = None) -> float:
    """The cosine floor that actually applies to a given embedding provider.

    MIN_RELEVANCE_SCORE is a SEMANTIC threshold. It was measured on the real
    model, where a relevant Persian query lands at 0.72-0.76 and gibberish at
    0.31-0.37 - so 0.5 separates the two. It only means anything if the score it
    filters is a semantic score.

    The 'mock' provider is a sha256 stub with no semantics at all: different
    strings produce independent vectors, so the cosine similarity between a
    question and ANY document is |s| <= 0.03 (measured on this checkout with
    backend.knowledge.embeddings._mock_vector at 1024 dimensions). Applying 0.5
    there rejects every hit, so a file that was uploaded, discovered, chunked and
    embedded - fully present and fully indexed - still answers that there was no
    document in the context sent with the question. That is not a hypothetical
    configuration: embedding_provider defaults to 'mock' (backend/config.py) and
    the dev deployment does not override it, so the floor alone made the whole
    retrieval path report an empty knowledge base.

    A provider whose score carries no semantics therefore gets no floor at all.
    Not zero either: the stub score is a cosine similarity between independent
    vectors, so it scatters around zero - measured samples were -0.0216,
    -0.0017, 0.008 and 0.0148 - and a floor of 0.0 would still throw away every
    document that landed on the negative half, which is about half of them.
    NO_SEMANTIC_FLOOR is below the bottom of the cosine range, so nothing is
    filtered and the candidate ranking (hash noise under this provider) is
    returned as-is. Ranked hits still come back, and the response reports the
    provider and the floor that was used, so a deployment running the stub is
    visible instead of silently answering that no documents exist.
    """
    name = provider if provider is not None else get_settings().embedding_provider
    if name == "mock":
        return NO_SEMANTIC_FLOOR
    return MIN_RELEVANCE_SCORE


async def _indexing_state(
    session: AsyncSession, organization_id, user_id, is_admin: bool
) -> dict:
    """How much readable knowledge exists, split by prepared vs preparing.

    Only called when a search found nothing: it is the difference between "this
    organization has no documents", "the documents are still being prepared" and
    "the documents are ready but none of them answer this question". Those three
    looked identical to the caller before, and the PO read the first one as
    "my file was lost".
    """
    rows = (
        await session.execute(
            select(KnowledgeAsset.status, func.count())
            .where(
                KnowledgeAsset.organization_id == organization_id,
                KnowledgeAsset.deleted_at.is_(None),
                visible_to(user_id, is_admin),
            )
            .group_by(KnowledgeAsset.status)
        )
    ).all()
    counts = {status: int(count) for status, count in rows}
    return {
        "ready": counts.get("ready", 0),
        "preparing": counts.get("queued", 0),
        "failed": counts.get("failed", 0),
    }


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
    #
    # relevance_floor() is provider-aware: the floor is a SEMANTIC threshold and
    # the mock provider produces non-semantic scores, so applying it there
    # rejected every hit and reported an empty knowledge base for content that
    # was fully indexed. See the function.
    floor = relevance_floor(settings.embedding_provider)
    hits = [hit for hit in candidates if hit["score"] >= floor]
    if len(hits) < MIN_RELEVANCE_HITS:
        hits = []
    # The honest half of an empty answer (PO report 2026-09-15: a file was added,
    # the answer said no document was sent with the question). An empty result
    # list cannot say WHY it is empty, so the three cases are named here: there
    # are no documents, the documents are still being prepared, or documents are
    # ready and none of them answers this question. Only computed when nothing
    # was found - the happy path pays no extra query.
    status = "ok"
    indexing = None
    if not hits:
        indexing = await _indexing_state(session, organization_id, user_id, is_admin)
        if indexing["ready"] == 0 and indexing["preparing"] == 0 and indexing["failed"] == 0:
            status = "no_documents"
        elif indexing["ready"] == 0:
            status = "documents_preparing"
        else:
            status = "no_match"
    await record_audit(
        session,
        "knowledge.search",
        organization_id=organization_id,
        detail={
            "query_chars": len(query),
            "top_k": limit,
            "hits": len(hits),
            "candidates": len(candidates),
            "floor": floor,
            "provider": settings.embedding_provider,
            "status": status,
        },
    )
    return {
        "query_chars": len(query),
        "results": hits,
        # Additive diagnostics. "results" keeps its shape and meaning for every
        # existing caller (the search API and the execution cycle branch on
        # len(results)); these two keys let a client tell "nothing to search"
        # from "nothing relevant" and show the user which one it is.
        "status": status,
        "provider": settings.embedding_provider,
        "relevance_floor": floor,
        "indexing": indexing,
    }
