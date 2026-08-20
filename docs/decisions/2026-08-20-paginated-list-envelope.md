# Decision: Paginated list response envelope (`{items, meta}`)

- **Date:** 2026-08-20
- **Status:** Accepted
- **Task:** S1-18 (Sprint-1 fix) — `GET /documents` pagination + response-envelope decision
- **Scope:** Backend thin API (v0.1) + `docs/openapi.yaml` (the single source of truth)

## Context

`GET /api/v1/documents` returned a bare JSON array with no paging, sorting,
filtering, or item count. Two problems were coupled (api-platform G4, backend #5):

1. The list could not be paged/sorted/filtered by clients, and
2. there was no formalized response shape for *list* endpoints — the codebase had
   no documented convention for a success envelope (the error envelope `{error,
   message, auditLogged}` is already formalized in ADR-002 / `openapi.yaml`).

The Sprint-1 board (S1-18) gave two options: implement pagination returning
`meta.total`, **or** record a documented decision to defer. Because the fix is
small and the endpoint is the only list endpoint in v0.1, we implement now.

## Decision

1. **Paginate `GET /api/v1/documents`** with query parameters:
   - `page` (integer ≥ 1, default `1`)
   - `pageSize` (integer 1..100, default `20`)
   - `sort` (allowlisted key, optional `-` prefix for descending; default
     `-createdAt`; unknown keys fall back to the default rather than erroring)
   - `filter` (case-insensitive substring match on `filename`)
   - `status` (exact filter on one of `detected|processing|ready|failed`)

2. **Adopt the envelope `{items, meta}`** for paginated list responses, where
   `meta` is `{total, page, pageSize, totalPages}` and `total` is the *full*
   result-set size before paging.

3. **Formalize the divergence:** the bare-array convention is superseded for
   list endpoints. This is the canonical shape going forward; future list
   endpoints (search, audit, etc.) reuse `PageMeta` / the same envelope.

## Rationale

- `meta.total` (not `items.length`) is what clients need to render page controls
  without fetching every page (api-platform G4 acceptance criterion).
- Sorting is restricted to a static allowlist of columns so client input is never
  interpolated into SQL (defends against sort-key injection).
- A dedicated `PageMeta`/`DocumentPage` schema keeps the contract explicit and
  reusable.

## Consequences

- **Breaking change (v0.x, pre-stable):** the response body of `GET /documents`
  changed from a bare array to `{items, meta}`. Consumers (frontend wizard) must
  read `items`. The frontend is refactored independently (S1-14) and re-tested.
- Existing ingestion tests were updated to the new envelope; new tests cover
  paging math, sort, filter, status, and 422 validation.
- `openapi.yaml` documents the new `DocumentPage`/`PageMeta` schemas and query
  parameters.

## Alternatives considered

- **Defer pagination + record only a decision** — rejected: the endpoint is the
  sole list surface and the fix is low-risk.
- **Offset/limit (cursor-free) only, no `meta.total`** — rejected: the AC and the
  standard require `meta.total`.
- **Keyset/cursor pagination** — deferred to a later epic (no stable sort keys
  beyond `id` today, and offset/limit is sufficient for v0.1 volume).
