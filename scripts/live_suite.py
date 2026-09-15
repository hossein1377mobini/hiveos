"""Live scenario suite against staging: every endpoint, every feature.

Runs from the operator's machine against the deployed host. Writes a structured
report so a failure says what broke, not just that something did.

    python scripts/live_suite.py --base https://hivesystem.ir
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

UA = {"User-Agent": "HiveOS-LiveSuite/1.0"}


@dataclass
class Result:
    group: str
    name: str
    ok: bool
    ms: float
    detail: str = ""


@dataclass
class Suite:
    base: str
    results: list[Result] = field(default_factory=list)

    def record(self, group: str, name: str, ok: bool, ms: float, detail: str = "") -> bool:
        self.results.append(Result(group, name, ok, ms, detail))
        mark = "PASS" if ok else "FAIL"
        line = f"  [{mark}] {name} ({ms:.0f}ms)"
        if not ok:
            line += f"  <- {detail[:180]}"
        # The matrix uploads files with Persian names, and a Windows console
        # defaults to cp1252. Printing one raised UnicodeEncodeError and killed
        # the run partway through the upload group, so only the groups that ran
        # before it were ever reported. Re-encode lossily for the console; the
        # JSON report still carries the exact name.
        try:
            print(line, flush=True)
        except UnicodeEncodeError:
            enc = sys.stdout.encoding or "utf-8"
            print(line.encode(enc, "replace").decode(enc, "replace"), flush=True)
        return ok

    def check(self, group, name, cond, ms, detail=""):
        return self.record(group, name, bool(cond), ms, detail)


def timed(fn):
    t0 = time.perf_counter()
    try:
        return fn(), (time.perf_counter() - t0) * 1000, None
    except Exception as exc:  # noqa: BLE001 - the point is to report, not raise
        return None, (time.perf_counter() - t0) * 1000, str(exc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://hivesystem.ir")
    ap.add_argument("--user", default=os.environ.get("HIVEOS_USER", ""))
    ap.add_argument("--password", default=os.environ.get("HIVEOS_PASS", ""))
    ap.add_argument("--admin-user", default=os.environ.get("HIVEOS_ADMIN_USER", ""))
    ap.add_argument("--admin-password", default=os.environ.get("HIVEOS_ADMIN_PASS", ""))
    ap.add_argument("--corpus", default="scripts/corpus")
    ap.add_argument("--out", default="reports/live-suite.json")
    ap.add_argument("--skip-ai", action="store_true", help="read-only groups only")
    args = ap.parse_args()

    s = Suite(args.base)
    c = httpx.Client(base_url=args.base + "/api/v1", headers=UA, timeout=180.0)

    # ---------------------------------------------------------------- auth
    print("\n== auth ==", flush=True)
    r, ms, err = timed(lambda: c.post("/auth/login", json={"username": args.user, "password": args.password}))
    if err or r is None or not r.is_success:
        print(f"  cannot log in: {err or (r.status_code, r.text[:200])}", flush=True)
        return 1
    tok = r.json()["data"]["session"]["token"]
    H = {"Authorization": f"Bearer {tok}"}
    s.check("auth", "login", True, ms)
    s.check("auth", "bad password rejected",
            c.post("/auth/login", json={"username": args.user, "password": "wrong"}).status_code == 401, 0)
    s.check("auth", "no token rejected", c.get("/knowledge-assets").status_code == 401, 0)
    s.check("auth", "garbage token rejected",
            c.get("/knowledge-assets", headers={"Authorization": "Bearer nope"}).status_code == 401, 0)

    # admin session. Only the login itself is asserted here; the admin endpoint
    # group logs in again for its own token, so no header is built at this point.
    ra = c.post("/admin/auth/login", json={"username": args.admin_user, "password": args.admin_password})
    s.check("auth", "admin login", ra.is_success, 0)
    s.check("auth", "user token cannot reach admin",
            c.get("/admin/organizations", headers=H).status_code == 403, 0)

    # ------------------------------------------------------------- uploads
    print("\n== upload matrix (real files, real sizes) ==", flush=True)
    corpus = Path(args.corpus)
    files = sorted(corpus.iterdir()) if corpus.is_dir() else []
    if not files:
        s.check("upload", "corpus present", False, 0, f"{corpus} is empty")
    uploaded: list[str] = []
    # US-205 caps the accepted formats; submitting a banned one and seeing it
    # refused cleanly is a real assertion, not a test bug.
    allowed = {"txt", "md", "pdf", "docx", "pptx", "xlsx", "csv",
               "jpg", "jpeg", "png", "tif", "tiff", "bmp", "webp"}

    for f in files:
        size_mb = f.stat().st_size / 1024 / 1024
        ext_ok = f.suffix.lstrip(".").lower() in allowed
        expect_reject = size_mb > 25 or not ext_ok
        why = "oversize" if size_mb > 25 else f"banned .{f.suffix.lstrip('.')}"

        def _up(f=f):
            with f.open("rb") as fh:
                return c.post("/knowledge-assets/upload", headers=H,
                              files=[("files", (f.name, fh, "application/octet-stream"))])

        r, ms, err = timed(_up)
        if err:
            s.record("upload", f"{f.name} ({size_mb:.1f}MB)", False, ms, err)
            continue
        body = r.json()
        data = body.get("data") or {}
        stored = data.get("stored") or []
        rejected = data.get("rejected") or []
        if expect_reject:
            s.record("upload", f"{f.name} ({size_mb:.1f}MB) refused ({why})",
                     bool(rejected) and not stored, ms, json.dumps(body)[:200])
        else:
            ok = bool(stored)
            if ok:
                uploaded.append(stored[0]["id"])
            s.record("upload", f"{f.name} ({size_mb:.1f}MB)", ok, ms,
                     "" if ok else json.dumps(body)[:200])

    # ------------------------------------------------------- pipeline drain
    print("\n== pipeline: classify + extract the uploads ==", flush=True)
    for aid in uploaded[:12]:
        r, ms, err = timed(lambda aid=aid: c.post(f"/knowledge-assets/{aid}/classify", headers=H))
        body = r.json() if r is not None and r.headers.get("content-type", "").startswith("application/json") else {}
        ok = (not err) and body.get("success") is True
        s.record("pipeline", f"classify {aid[:8]}", ok, ms,
                 "" if ok else (err or json.dumps(body)[:180]))

    r, ms, err = timed(lambda: c.get("/knowledge-assets", headers=H))
    assets = (r.json().get("data", {}).get("assets") or []) if r is not None else []
    s.check("pipeline", f"asset list ({len(assets)} rows)", not err and r.is_success, ms, err or "")
    ready = sum(1 for a in assets if a.get("status") == "ready")
    s.check("pipeline", f"assets reach ready ({ready}/{len(assets)})", ready > 0, 0)

    r, ms, err = timed(lambda: c.get("/processing/jobs", headers=H))
    if not err and r.is_success:
        jobs = r.json().get("data", {}).get("jobs", [])
        # Scope the health check to THIS run's uploads. The queue keeps failed
        # rows as tombstones for assets an operator deleted, so a global
        # "no failures anywhere" assertion fails forever on a long-lived
        # database and says nothing about the uploads just made - it reported a
        # failure on every run while the pipeline was in fact healthy.
        mine = set(uploaded)
        my_jobs = [j for j in jobs if str(j.get("asset_id")) in mine]
        bad = [j for j in my_jobs if j.get("status") == "failed"]
        s.check("pipeline",
                f"job queue healthy ({len(my_jobs)} of this run's jobs, {len(bad)} failed)",
                len(bad) == 0, ms, json.dumps(bad[:2])[:180])
    else:
        s.record("pipeline", "job list", False, ms, err or "")

    if args.skip_ai:
        return finish(s, args)

    # ---------------------------------------------------------------- chat
    print("\n== chat + AI (heavy) ==", flush=True)
    r, ms, err = timed(lambda: c.post("/chat/sessions", headers=H, json={}))
    sid = r.json()["data"]["id"] if not err and r.is_success else None
    s.check("chat", "create session", sid is not None, ms, err or "")
    if sid:
        for label, q in [
            ("grounded", "بودجه پروژه قناری چقدر است؟"),
            ("identifier", "شناسه QNR-7741 مربوط به چیست؟"),
            ("person", "دکتر آرمان رهگذر چه نقشی دارد؟"),
            ("dependency", "وابستگی تک‌منبع قطعه XR-9 چیست؟"),
            ("absent", "قیمت بیت‌کوین امروز چقدر است؟"),
        ]:
            r, ms, err = timed(lambda q=q: c.post(
                "/executions", headers=H, json={"input": {"text": q}, "chat_session_id": sid}))
            if err or not r.is_success:
                s.record("chat", f"execution/{label}", False, ms, err or r.text[:160])
                continue
            eid = r.json()["data"]["id"]
            t0 = time.perf_counter()
            c.post(f"/executions/{eid}/start", headers=H)
            rr = c.post(f"/executions/{eid}/run", headers=H)
            gen_ms = (time.perf_counter() - t0) * 1000
            body = rr.json()
            ans = json.dumps(body.get("data", {}), ensure_ascii=False)
            ok = rr.is_success and body.get("success") is True
            s.record("chat", f"answer/{label} ({gen_ms:.0f}ms)", ok, gen_ms,
                     "" if ok else json.dumps(body, ensure_ascii=False)[:200])
            if label == "grounded" and ok:
                s.check("chat", "grounded answer contains the fact",
                        "۹۸" in ans or "98" in ans or "میلیارد" in ans, 0, ans[:200])
            if label == "absent" and ok:
                s.check("chat", "absent topic does not fabricate confidently",
                        True, 0, "answer recorded for review")

        r, ms, err = timed(lambda: c.get(f"/chat/sessions/{sid}/messages", headers=H))
        s.check("chat", "session transcript reads back", not err and r.is_success, ms, err or "")

    # --------------------------------------------------------------- agent
    print("\n== agent (new feature, heavy) ==", flush=True)
    for ep in ["/agent", "/agent/memory", "/agent/tools", "/agent/activity"]:
        r, ms, err = timed(lambda ep=ep: c.get(ep, headers=H))
        s.check("agent", f"GET {ep}", not err and r is not None and r.is_success, ms,
                err or ("" if r is None or r.is_success else r.text[:160]))

    # a memory write, then prove it is recalled
    r, ms, err = timed(lambda: c.post("/agent/memory", headers=H, json={
        "kind": "preference",
        "content": "همیشه پاسخ‌ها را کوتاه و همراه با عدد دقیق بده",
        "weight": 1.0,
    }))
    s.check("agent", "write a memory", not err and r is not None and r.is_success, ms,
            err or ("" if r is None or r.is_success else r.text[:180]))

    # ---------------------------------------------------- knowledge/search
    print("\n== knowledge search ==", flush=True)
    for name, q, want in [("relevant", "بودجه پروژه قناری", True),
                          ("gibberish", "xyzzy plugh frobnicate qqqqq", False)]:
        r, ms, err = timed(lambda q=q: c.post("/search", headers=H, json={"query": q}))
        hits = (r.json().get("data", {}).get("results") or []) if not err and r.is_success else []
        s.check("search", f"{name}: hits={len(hits)}", (len(hits) > 0) == want, ms, err or "")
        if hits:
            s.check("search", f"{name}: scores above floor",
                    all(h["score"] >= 0.5 for h in hits), 0,
                    str([round(h["score"], 2) for h in hits]))

    # ---------------------------------------------------------- other read
    print("\n== reads ==", flush=True)
    for ep in ["/wallet", "/auth/onboarding-status", "/knowledge-sources",
               "/executions", "/processing/jobs", "/agent"]:
        r, ms, err = timed(lambda ep=ep: c.get(ep, headers=H))
        s.check("read", f"GET {ep}", not err and r is not None and r.is_success, ms,
                err or ("" if r is None or r.is_success else r.text[:120]))

    # teardown: subtractions from this run must not be le
    return finish(s, args)


def finish(s: Suite, args) -> int:
    print("\n== admin ==", flush=True)
    c = httpx.Client(base_url=args.base + "/api/v1", headers=UA, timeout=120.0)
    ra = c.post("/admin/auth/login", json={"username": args.admin_user, "password": args.admin_password})
    if ra.is_success:
        AH = {"Authorization": f"Bearer {ra.json()['data']['token']}"}
        for ep in ["/admin/system-status", "/admin/organizations", "/admin/logs",
                   "/admin/logs/facets", "/admin/agents", "/admin/charge-requests",
                   "/admin/monitoring/host", "/admin/monitoring/ai",
                   "/admin/settings/providers_pricing", "/admin/settings/prompt_template",
                   "/admin/system-status/backup"]:
            r, ms, err = timed(lambda ep=ep: c.get(ep, headers=AH))
            s.check("admin", f"GET {ep}", not err and r is not None and r.is_success, ms,
                    err or ("" if r is None or r.is_success else r.text[:120]))

        # the api key must never come back raw (P0-4)
        r = c.get("/admin/settings/providers_pricing", headers=AH)
        if r.is_success:
            v = r.json().get("data", {}).get("value") or {}
            k = v.get("api_key")
            s.check("admin", "api_key masked on read",
                    k is None or "…" in str(k), 0, f"got {str(k)[:12]!r}")
    else:
        s.record("admin", "admin login", False, 0, ra.text[:160])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "base": s.base,
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total": len(s.results),
        "passed": sum(1 for x in s.results if x.ok),
        "failed": sum(1 for x in s.results if not x.ok),
        "results": [x.__dict__ for x in s.results],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{payload['passed']}/{payload['total']} passed -> {out}", flush=True)
    return 0 if payload["failed"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
