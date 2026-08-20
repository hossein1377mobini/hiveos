# Decision: docs contract alignment + SSoT drift flags (S1 / docs-ownership pass)

- **Date:** 2026-08-20
- **Status:** Accepted (applied changes) + two **open decision points** for PO/CEO (flagged, not acted)
- **Task:** s4/docs-sso — HiveOS documentation-owner pass over `docs/`, `docs/openapi.yaml`, `README.md`
- **Scope:** docs only (no backend Python logic, no feature removal). CEO-governed `Dropbox/Hive/doc/` left untouched.

## Context

`docs/openapi.yaml` (v0.2.0) is the single source of truth for the Epic-01 API
contract and is asserted 1:1 against `backend/app/schemas.py`. A doc-ownership
review compared (a) the contract against the live backend routers, (b) the README
against reality, and (c) the repo `docs/` against ADR-002's "docs/ is the sole
official source of documentation" rule.

Three findings:

1. **Contract gap:** the backend serves `GET /api/v1/healthz` (`app/api/v1/health.py`)
   and `README.md` documents it in Getting Started, but `openapi.yaml` omits it.
2. **BYOK vs ADR-020:** `AIModelConfiguration.apiKey` is present in *both* the
   backend (`schemas.py`, `models.py ai_api_key_enc`, `conftest.py`) and the
   contract, while ADR-020 (accepted, PO decision) removes BYOK in favour of
   managed access + credit wallet.
3. **SSoT location:** repo `docs/` is near-empty while ADR-002 declares it the sole
   official documentation source; the canonical ADRs/Standards/Architecture actually
   live in `Dropbox/Hive/doc/` (CEO-governed).

## Decision

### Applied (docs-only, this branch)

1. **Add `GET /api/v1/healthz` to `openapi.yaml`** (Operations tag, public,
   `{status: ok}`) so the contract SSoT matches the served endpoint and the README.
2. **Flag the BYOK drift inline** in `AIModelConfiguration.description`
   (openapi.yaml) — a note, not a schema change, so the contract stays 1:1 with the
   live code.
3. **Rewrite `docs/README.md`** from a skeleton placeholder to a real index + SSoT
   relationship + open decision points.
4. **Correct `README.md`** (root): accurate `docs/` description and current backend
   test count (89, not 61).

### Flagged — open decision points (NOT acted; need PO/CEO)

- **DP-1 — BYOK / `apiKey` removal (ADR-020).** Removing `apiKey` from the contract
  requires the backend code (router/metering/billing) to migrate first; today it
  would desync `openapi.yaml` from `schemas.py`/`models.py` and break the test
  fixtures. This is a code change + CEO decision, out of docs-owner scope.
- **DP-2 — SSoT location (repo `docs/` vs `Dropbox/Hive/doc/`).** ADR-002 says
  `docs/` is the sole official source; in practice the governing ADRs/standards are
  CEO-maintained in Dropbox. Deciding the canonical mechanism (mirror / link / full
  migration) is a CEO decision. Dropbox files were not modified.

## Consequences

- Contract now documents the full served surface (13 → 14 paths), incl. `healthz`.
- The BYOK drift is visible where the schema lives, instead of silently diverging.
- Repo `docs/` has an accurate index and the SSoT tension is recorded in-repo
  (not imposed on the Dropbox-governed files).

## Alternatives considered

- **Remove `apiKey` from `openapi.yaml` now** — rejected: desyncs the SSoT from live
  code before the backend migrates; flagged as DP-1 instead.
- **Mirror the full Dropbox `doc/` into repo `docs/`** — rejected: duplicates the
  CEO-governed SSoT and invites drift; flagged as DP-2.
- **Copy ADR-020 into the repo** — rejected: Dropbox is the canonical ADR home; the
  repo references it rather than re-hosting it.
