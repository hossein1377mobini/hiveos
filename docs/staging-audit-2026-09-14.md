# HiveOS staging — deep test findings (read-only audit)

Date: 2026-09-14 · Image: `hiveos/api:ci-7399cee` · Migration: `0028 (head)`
Audited: main app + admin panel + infra. **No code was changed.**

---

## P0-1 — Upload is broken above 1 MB (nginx), and the error is unreadable

**Symptom the PO saw:** "پاسخ سرور قابل خواندن نبود" / "ارتباط با سرور برقرار نشد".

**Cause.** nginx sets no `client_max_body_size`, so it keeps the 1 MB default.
The app allows 25 MB (`config.py: upload_max_file_mb = 25`). Anything between
1 MB and 25 MB is killed by nginx before FastAPI ever sees it.

Proof (measured ladder, `POST /api/v1/knowledge-assets/upload`):

| size | result |
|---|---|
| 900 KB | 200 (app-level reject, correct) |
| 1000 KB | 200 |
| **1024 KB** | **413 text/html from nginx/1.24.0** |
| 4096 KB | 413 text/html |
| 25600 KB | 413 text/html |

`nginx.conf` has **zero** `client_max_body_size` directives (`nginx -T` confirms).

**Why the message is wrong.** nginx returns an **HTML** error page. The client does
`await response.json()` (`frontend/src/api/client.ts:75`), the parse throws, and it
throws `CLIENT_BAD_RESPONSE` → "پاسخ سرور قابل خواندن نبود". The 413 mapping that
already exists (`errors.ts:140`) is **never reached**, because the status is discarded
in the catch block at `client.ts:78-82`.

**Fix.**
1. nginx: add `client_max_body_size 26m;` in the `http` block (or both `server` blocks)
   in `/etc/nginx/sites-available/hiveos`. Must be ≥ the app cap, with headroom for
   multipart overhead. Keep it in the repo's nginx template too, not just on the server.

   **STATUS.** The repo's own nginx template **already sets it**:
   `deploy/nginx.conf:26` has `client_max_body_size 50m;` — larger than the app's 25 MB
   cap, so the multipart headroom is covered. The finding is therefore **server-only**:
   the hand-maintained `/etc/nginx/sites-available/hiveos` did not have the directive.
   Nothing to change in the repository for this one.
2. Client: in the `catch` at `client.ts:76`, keep `response.status` and prefer
   `BY_STATUS[status]` when the body is not JSON. A 413 should say "حجم فایل بیش از حد
   مجاز است", not "پاسخ سرور قابل خواندن نبود".
3. Optional but better: return a JSON envelope for 413 (`error_page 413`).

---

## P0-2 — Client-folder auto-sync hits the same 1 MB wall

The core product flow (Electron client → `POST /knowledge-sources/client-folder/files/{asset_id}`)
is subject to the same nginx limit. Verified: a 2 MB file returns the identical
`413 text/html`.

**Consequence:** any folder containing a file >1 MB silently fails to sync. The 12-file
test corpus happens to be all sub-1 MB, which is why this was not caught earlier.

Same fix as P0-1 (the nginx limit is the whole cause).

---

## P0-3 — "پویش دستی" (Scan Now) always fails on client_folder sources

**Proof.** `sudo grep` of the nginx access log shows the PO pressing it repeatedly,
every attempt 400:

```
POST /api/v1/knowledge-sources/ac0ccaef-.../scan -> 400  (x8, 17:16–17:46)
```

Reproduced live: `POST /knowledge-sources/{id}/scan` → 400
`INGESTION_PATH_NOT_READABLE` ("The server cannot read this folder.").

**Cause.** `Knowledge.tsx:188-202` calls `/knowledge-sources/{id}/scan` **regardless of
source type**. The backend only accepts `local_folder` there
(`service.py:464-477`). A `client_folder` source holds a path on the *user's own
machine*, which the server can never read — so this button can never work for it.

**Fix.** In `Knowledge.tsx`, branch on `source.source_type`:
- `client_folder` → do not call `/scan`; trigger the client-side sync
  (`syncClientFolder`) or show "همگامسازی از رایانهٔ شما انجام میشود" and hide the button.
- `local_folder` → keep the current call.
Also hide/disable the button rather than letting the user press a control that is
guaranteed to error.

---

## P0-4 — Full LLM API key returned unmasked to the admin panel

`GET /api/v1/admin/settings/providers_pricing` returns the raw key:

```
api_key value len=51 prefix=aa-FanBj masked?=False
```

**Impact.** Any admin session, any browser devtools, any log of that response exposes a
live billable key. The PO already knows the key leaked; this makes it leak on every
settings page load.

**Fix.** Mask on read (`aa-FanBj…SV25`) and write a sentinel on update: if the client
PUTs back the masked value or an empty string, keep the stored key. Verify the key is
never included in `/admin/system-status` or any log line.

---

## P1-5 — No client-side size check before upload

`Knowledge.tsx` uploads whatever is picked. The server's own limit
(`upload_max_file_mb`, exposed via `/client-folder/sync-plan` as `max_file_mb`) is never
consulted on the UI path. The user waits for a full upload, then gets the cryptic P0-1
error.

**Fix.** Read `max_file_mb` (already served) once, filter/reject oversized files in the
picker with a Persian message *before* sending, and show the limit in the dropzone.

---

## P1-6 — Auto-sync fetches `max_file_mb` and ignores it

`frontend/src/lib/autoSync.ts:21` declares `max_file_mb` on `SyncPlan`; `tick()` (line
49-50) never reads it. `folderSync.ts` uploads every pending file with no size gate.

**Fix.** In `syncClientFolder`, compare `entry.size_bytes` against the plan's
`max_file_mb` and report oversize files in the existing `failed[]`/`rejected[]` shape
instead of attempting the POST. Avoids burning the 30 req/min knowledge limiter on
files that cannot succeed.

---

## P1-7 — Rate limiter is bypassable by spoofing `X-Forwarded-For`

`config.py:133` ships `trusted_proxies: str = "*"` and the staging `.env` does **not**
override it. `rate_limit.py:client_key()` therefore trusts the leftmost XFF from *any*
peer. The API port is bound to `127.0.0.1:8100` only, but anything on the host that can
reach it can forge the header — and nginx passes it straight through
(`proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for`).

**Proof** (limit is 30/min on `/search`):

```
rotating X-Forwarded-For -> 200:40  429:0     # unlimited
fixed                       -> 200:30  429:10    # limit works
```

**Fix.** Set `TRUSTED_PROXIES=127.0.0.1` in `/opt/hiveos/app/.env` (and in the repo's
staging env template). Default of `"*"` in `config.py` should be a narrow value, since a
misspelled deployment silently disables rate limiting.

**STATUS (repo side done).** Root cause was upstream of `.env`: a hand-edited value
would not have survived anyway, because `scripts/deploy/remote-deploy.sh:35-48` rewrites
`.env` from a heredoc on **every deploy**, and that heredoc did not mention
`TRUSTED_PROXIES` at all. Fixed at the source:
- `remote-deploy.sh` now emits `TRUSTED_PROXIES=127.0.0.1` into the generated `.env`.
- `deploy/.env.example` no longer ships `HIVEOS_TRUSTED_PROXIES=*`.
The server's live `.env` still needs one deploy (or a manual edit) to pick this up.

---

## P1-8 — CORS origin does not match the real domain

`CORS_ORIGINS=https://staging.hivesystem.ir` but the live host is
`https://hivesystem.ir`.

Measured:
```
Origin: https://staging.hivesystem.ir  -> access-control-allow-origin: https://staging.hivesystem.ir
Origin: https://hivesystem.ir          -> (no CORS headers)
```

Same-origin browser traffic is unaffected (that is why the app works), but any
cross-origin client — a future separate admin host, a desktop build with a different
origin — is silently blocked.

**Fix.** Set `CORS_ORIGINS=https://hivesystem.ir` (comma-separate if both are needed).

**STATUS (repo side done).** Root cause found: `scripts/deploy/remote-deploy.sh:45`
hard-coded `CORS_ORIGINS=https://staging.hivesystem.ir` inside the heredoc that regenerates
`.env` on every deploy — so the wrong value was being re-written each time, and editing
it on the server alone would have been reverted. Fixed at the source:
- `remote-deploy.sh` now emits `CORS_ORIGINS=https://hivesystem.ir`.
- `deploy/.env.example` carries the apex origin with a comment explaining why.
The server's live `.env` still needs one deploy (or a manual edit) to pick this up.

---

## P2-9 — Search has no relevance floor

Gibberish returns a full page of results:

| query | hits | scores |
|---|---|---|
| بودجه پروژه قناری | 5 | 0.72 – 0.76 |
| xyzzy plugh frobnicate qqqqq | **5** | 0.31 – 0.37 |

There is a clear separation between the two bands. The API always returns `top_k`, so a
user asking about something not in the knowledge base still sees five confident-looking
citations.

**Fix.** Add a similarity floor (≈0.5 looks safe given the measured gap) plus a
"minimum hits" rule, and let the answer path say "در دانش سازمان چیزی پیدا نشد" when
nothing clears it. The off-topic honesty already exists in the generator — this makes
the retrieval layer agree.

---

## P2-10 — Cloudflare blocks non-browser User-Agents (403)

```
python3 urllib  -> HTTP 403 Forbidden
curl (any UA)   -> 200
browser UA      -> 200
```

Any server-side monitor, uptime check, or script that hits the public host with a
default library UA gets 403 — including our own tooling. This is a Cloudflare-side
setting, not an app bug.

**Fix.** Add a WAF skip/bypass rule for the health endpoints, or give monitoring a
known UA on an allowlist.

---

## P2-11 — Backups are local-only and short-retention

```
/opt/hiveos/backups/  4 dumps, newest hiveos-20260914-033001.dump (18.5 h old)
root cron: 30 3 * * * /opt/hiveos/scripts/db-backup.sh
```

Backups live on the same disk as the database. A disk failure or a bad `rm` loses both.

**Fix.** Push to off-host storage (restic/rclone to S3-compatible). Keep the local copy
for fast restore. This was already on the open list — reconfirmed.

---

## P2-12 — Tombstone assets pollute the list (24 failed, 5 queued)

```
knowledge_assets by status: ready 33 | failed 24 | queued 5
processing_jobs failed 24: ASSET_FILE_MISSING "The asset file cannot be found."
```

All 24 are from 12:00–13:04 today, from my earlier test runs where files were copied
onto the host without being visible inside the container. **Not a live code bug** — but
two things are worth fixing:

1. The failed rows are never cleaned up and now outnumber working ones in the admin
   view. A housekeeping job (or a "purge failed" admin action) is needed.
2. ~~`ASSET_FILE_MISSING` is not in the client's `MESSAGES` map.~~ **STALE — already
   fixed.** The map lives at `frontend/src/api/errors.ts` (not `lib/`), and
   `ASSET_FILE_MISSING` has carried the Persian string
   "فایل این سند روی سرور پیدا نشد." since before this audit. Verified by diffing
   every `ApiError(code)` raised in `backend/backend/**` against the client map:
   **61 backend codes, 100 mapped strings, 0 gaps.** The generic fallback the audit
   saw was therefore not a missing string.

The 5 `queued` assets are the images that succeeded as `ready` later; verify they are
genuinely duplicates before deleting.

---

## P3-13 — Dead nginx listener on 8080

`listen 80 default_server; listen 8080; listen 2052;` — a leftover from an earlier
layout. 8080 is **not** in ufw, so it is not externally reachable (verified: only
22/80/443/2052 are allowed). Not a vulnerability today; remove it so a future ufw
change cannot expose the app over plain HTTP.

---

## Verified working (no action)

- Envelope contract holds on every error path tested; all messages Persian.
- Auth: wrong password / unknown user both 401 `AUTH_INVALID_CREDENTIALS` (no user
  enumeration); missing / malformed / empty bearer all 401; admin route with a **user**
  token correctly 403 `ADMIN_FORBIDDEN`.
- Tenant isolation: cross-org UUIDs on assets, chunks, metadata, download, executions,
  scan-history all correctly 404 — no leakage.
- Input validation: negative and zero wallet charge both 400; empty execution input 400
  with a precise message.
- OCR stack live: tesseract 5.3.0, fas/eng/osd all present, `/opt/models` 2.6 GB,
  embeddings + reranker local.
- All 33 ready assets; 12-chunk chat answers cite the corpus correctly
  ("۹۸ میلیارد ریال", "دکتر آرمان رهگذر").
- Agent subsystem live: memory persisted (`preference`, w=1.0), recalled on the next
  turn (hits=1), and the answer style actually changed.
- Admin GET sweep: all 12 endpoints 200; `PUT /admin/settings/{key}` round-trips.
- Backup cron ran; `/admin/system-status/backup` reports `state: ok`.
- Migrations at head 0028; all three agent tables present.
- nginx config syntax valid; no duplicate server blocks.

---

## Server-side remainder (needs one deploy, not a code change)

These four are now written correctly in the repo but the running staging host still
carries the old values, because the host's `.env` / nginx config is hand-maintained:

1. **P0-1/P0-2** — add `client_max_body_size 50m;` to `/etc/nginx/sites-available/hiveos`
   (the repo template already has it; the host config does not). Use `nginx -t` then
   `systemctl reload nginx`.
2. **P1-7** — `TRUSTED_PROXIES=127.0.0.1` in `/opt/hiveos/app/.env` (now also emitted by
   `remote-deploy.sh`, so the next deploy does it).
3. **P1-8** — `CORS_ORIGINS=https://hivesystem.ir` in the same `.env` (likewise now
   emitted by the deploy script).
4. **P2-10** — Cloudflare WAF: skip rule for the health endpoints, or allowlist a
   monitoring UA. Cloudflare-side, no repo change possible.
5. **P2-11** — off-host backup push (restic/rclone). Ops work, unchanged.
6. **P3-13** — drop the dead `listen 8080;` from the host's nginx server block.

---

## Suggested order for the developer

1. P0-1 nginx `client_max_body_size` + client 413 handling — unblocks the PO's report.
2. P0-2 same fix covers client-folder sync.
3. P0-3 Scan Now branch on source type.
4. P0-4 mask the API key.
5. P1-7 `TRUSTED_PROXIES` (security, one-line).
6. P1-5/P1-6 client-side size gate.
7. P1-8 CORS origin.
8. P2-9 search relevance floor.
9. P2-12 purge + missing error string.
10. P2-10, P2-11, P3-13 (ops).
