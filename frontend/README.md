# HiveOS Frontend (T-S0-5) — React 19 + Vite 7 + Tailwind CSS 4 + TypeScript

App-shell base for the HiveOS thin client (ADR-023). Placeholder layout only —
feature sections land with their epics (S1..S4, `hive/documentation/development-workflow.md` §8).

## Commands (run from `frontend/`)

| هدف | دستور |
|-----|-------|
| نصب وابستگی‌ها | `npm install` |
| اجرای dev (proxy `/api` → `http://127.0.0.1:8100`) | `npm run dev` |
| تست‌ها | `npm test` |
| build + type-check | `npm run build` |

## Dev flow

1. `docker compose -f infrastructure/docker-compose.yml up -d` (or run uvicorn from `backend/`).
2. `cd frontend && npm run dev` → open the printed localhost URL.
3. The health badge on the placeholder page must show «متصل» — that proves the
   `/api` proxy + backend wiring end to end.

## Conventions

- `src/styles.css` holds the design tokens (`hive/design/design-system.md` v0.4.0 §2);
  light mode only in v0.1 (PO decision). shadcn semantic aliases are pre-mapped.
- RTL is the document default (`index.html` `dir="rtl"`); use logical spacing
  (`ms-`, `me-`, `ps-`, `pe-`, `border-e`) — never physical left/right.
- User-facing copy follows `hive/product/terminology.md` §7 (Owner→«مدیر», …).
- No hardcoded config: API base is always same-origin `/api` (dev proxy +
  staging nginx give the same contract; ADR-022 nothing client-side anyway).
