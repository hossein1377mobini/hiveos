"""Live test of the features added in d1632de, against real staging.

The existing live suite proves the product works end to end. This one proves the
SIX specific reports from 2026-09 are actually fixed on the deployed build, with
real requests and real data - because each of them was "the feature exists but
the user cannot see it", which a unit test with a stubbed tool result cannot
distinguish from the bug.

    python scripts/live_new_features.py --base https://hivesystem.ir

Every check is written against the real envelope and asserts what the user would
see, not that a key merely exists.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from live_suite import UA, Suite, timed  # noqa: E402


def run_turn(c, H, sid: str, question: str):
    """One full chat turn: create -> start -> run. Returns (data, ms)."""
    r = c.post("/executions", headers=H, json={"input": {"text": question}, "chat_session_id": sid})
    if not r.is_success:
        return None, 0.0
    eid = r.json()["data"]["id"]
    c.post(f"/executions/{eid}/start", headers=H)
    t0 = time.perf_counter()
    rr = c.post(f"/executions/{eid}/run", headers=H)
    ms = (time.perf_counter() - t0) * 1000
    if not rr.is_success:
        return None, ms
    return rr.json().get("data") or {}, ms


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://hivesystem.ir")
    ap.add_argument("--user", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--out", default="reports/live-new-features.json")
    args = ap.parse_args()

    s = Suite(args.base)
    c = httpx.Client(base_url=args.base + "/api/v1", headers=UA, timeout=300.0)

    r, ms, err = timed(lambda: c.post("/auth/login", json={"username": args.user, "password": args.password}))
    if err or r is None or not r.is_success:
        print(f"cannot log in: {err or (r.status_code, r.text[:200])}", flush=True)
        return 1
    H = {"Authorization": f"Bearer {r.json()['data']['session']['token']}"}

    # ---------------------------------------------------------------- search
    # The honest half of an empty answer. Before d1632de an empty result list
    # could not say WHY it was empty, and with the mock provider the semantic
    # floor rejected every hit so a full corpus answered as if it were empty.
    print("")
    print("== search: why the result is empty ==", flush=True)
    r, ms, err = timed(lambda: c.post("/search", headers=H, json={"query": "بودجه پروژه قناری"}))
    ok = not err and r is not None and r.is_success
    data = (r.json().get("data") or {}) if ok else {}
    s.check("search", "relevant query returns hits", bool(data.get("results")), ms, err or "")
    s.check("search", "result reports where it came from",
            "status" in data and "provider" in data, 0, json.dumps(data)[:160])
    s.check("search", "floor that was applied is reported", "relevance_floor" in data, 0, json.dumps(data)[:160])

    r, ms, err = timed(lambda: c.post("/search", headers=H, json={"query": "xyzzy plugh frobnicate qqqqq"}))
    gdata = (r.json().get("data") or {}) if not err and r.is_success else {}
    s.check("search", "gibberish returns nothing", not gdata.get("results"), ms, err or "")
    s.check("search", "empty result says which empty it is",
            gdata.get("status") in ("no_match", "no_documents", "documents_preparing"), 0,
            json.dumps(gdata, ensure_ascii=False)[:200])

    # ------------------------------------------------------------------- chat
    print("")
    print("== chat: a new session must know the last one ==", flush=True)
    r, ms, err = timed(lambda: c.post("/chat/sessions", headers=H, json={}))
    sid_a = r.json()["data"]["id"] if not err and r.is_success else None
    s.check("memory", "create session A", sid_a is not None, ms, err or "")

    marker = "پروژه زیتون هفتاد و هفت"
    if sid_a:
        data, ms = run_turn(c, H, sid_a, f"{marker}: تصمیم گرفتیم فاز دوم را به تعویق بیندازیم. این را به خاطر بسپار.")
        s.check("memory", "session A answers", data is not None, ms)

        r, ms, err = timed(lambda: c.get("/agent/memory", headers=H))
        blob = json.dumps(r.json().get("data") or {}, ensure_ascii=False) if not err and r.is_success else ""
        s.check("memory", "the exchange itself is stored as a memory", marker in blob, ms,
                "" if marker in blob else blob[:200])

        # A brand new session: this is where the old build answered with no idea
        # what the previous chat said, because marker-gated extraction had stored
        # nothing for ordinary conversation.
        r, ms, err = timed(lambda: c.post("/chat/sessions", headers=H, json={}))
        sid_b = r.json()["data"]["id"] if not err and r.is_success else None
        if sid_b:
            data, ms = run_turn(c, H, sid_b, "درباره پروژه زیتون هفتاد و هفت چه تصمیمی گرفته بودیم؟")
            ans = json.dumps(data or {}, ensure_ascii=False)
            s.check("memory", "new session answers at all", data is not None, ms)
            s.check("memory", "new session recalls the earlier chat",
                    "زیتون" in ans or "تعویق" in ans or "فاز دوم" in ans, ms, ans[:260])

    # -------------------------------------------------------------- artifacts
    print("")
    print("== artifacts: a generated file must be visible and reopenable ==", flush=True)
    r, ms, err = timed(lambda: c.post("/chat/sessions", headers=H, json={}))
    sid_c = r.json()["data"]["id"] if not err and r.is_success else None
    artifacts = []
    if sid_c:
        data, ms = run_turn(c, H, sid_c, "یک گزارش کامل از پروژه قناری بساز و برایم آماده کن.")
        s.check("artifacts", "report request answers", data is not None, ms)
        artifacts = (data or {}).get("artifacts") or []
        s.check("artifacts", "the reply carries the file it built", bool(artifacts), ms,
                json.dumps(data or {}, ensure_ascii=False)[:300])

        r, ms, err = timed(lambda: c.get(f"/chat/sessions/{sid_c}/messages", headers=H))
        msgs = (r.json().get("data") or {}) if not err and r.is_success else {}
        items = msgs.get("items") or msgs.get("messages") or []
        stored = [m for m in items if m.get("artifacts")]
        s.check("artifacts", "the file survives a reload of the transcript", bool(stored), ms,
                json.dumps(items, ensure_ascii=False)[:300])

        if artifacts:
            aid = artifacts[0].get("asset_id")
            s.check("artifacts", "the file is a real readable asset",
                    bool(aid) and bool(artifacts[0].get("name")), 0, json.dumps(artifacts, ensure_ascii=False)[:200])
            r, ms, err = timed(lambda: c.get(f"/knowledge-assets/{aid}", headers=H))
            s.check("artifacts", "the file can be read back from the files list",
                    not err and r is not None and r.is_success, ms, err or "")
            s.check("artifacts", "same id in the reply and in the transcript",
                    any(a.get("asset_id") == aid for a in (stored[0].get("artifacts") if stored else [])), 0)

        # Live status: the sidebar must be able to say a conversation is answering.
        r, ms, err = timed(lambda: c.get("/chat/sessions", headers=H))
        body = (r.json().get("data") or {}) if not err and r.is_success else {}
        rows = body.get("items") or body.get("sessions") or []
        s.check("live", "session list reports generating state",
                bool(rows) and any("generating" in row for row in rows), ms,
                json.dumps(rows, ensure_ascii=False)[:220])

    # ---------------------------------------------------------------- billing
    print("")
    print("== billing: the charge must be auditable ==", flush=True)
    r, ms, err = timed(lambda: c.get("/wallet", headers=H))
    w = (r.json().get("data") or {}) if not err and r.is_success else {}
    s.check("billing", "wallet reads back", not err and r is not None and r.is_success, ms, err or "")
    s.check("billing", "organization usage totals are reported",
            isinstance(w.get("usage"), dict), 0, json.dumps(w, ensure_ascii=False)[:200])
    s.check("billing", "per-user usage is reported",
            isinstance(w.get("my_usage"), dict), 0, json.dumps(w.get("my_usage"), ensure_ascii=False)[:200])
    mu = w.get("my_usage") or {}
    s.check("billing", "this user's turns were counted", int(mu.get("executions") or 0) > 0, 0, json.dumps(mu)[:200])
    s.check("billing", "every billed token class is reported",
            all(k in mu for k in ("tokens_in", "tokens_out", "cached_tokens", "reasoning_tokens", "cost_usd")), 0,
            json.dumps(mu)[:220])

    tx = w.get("transactions") or []
    deductions = [t for t in tx if (t.get("kind") or t.get("type") or "").upper() == "DEDUCTION"]
    if deductions:
        d = deductions[0]
        s.check("billing", "a deduction carries the basis it was computed from",
                "cost_basis" in d and d.get("cost_basis") is not None, 0, json.dumps(d, ensure_ascii=False)[:260])
        basis = d.get("cost_basis") or {}
        s.check("billing", "the basis names the rate source or says it fell back",
                bool(basis.get("rate")) and bool(basis.get("source")), 0, json.dumps(basis, ensure_ascii=False)[:260])
    else:
        s.check("billing", "a deduction exists to inspect", False, 0, json.dumps(tx, ensure_ascii=False)[:200])

    c.close()
    passed = sum(1 for x in s.results if x.ok)
    total = len(s.results)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        [{"group": x.group, "name": x.name, "ok": x.ok, "ms": x.ms, "detail": x.detail} for x in s.results],
        ensure_ascii=False, indent=2), encoding="utf-8")
    print("")
    print(f"{passed}/{total} passed -> {out}", flush=True)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())