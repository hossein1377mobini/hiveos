"""HiveOS v0.1 ingestion folder watcher (RG-03, zero-open bundle).

Watches a local folder and pushes every new/changed supported file to the
organization's knowledge base via the API (multipart upload), so the
folder integration works without any server-side path access.

Usage:
    python scripts/ingest_watcher.py --folder C:/docs --base-url http://localhost:8080 \
        --username owner.one --password ***

Env alternative: HIVEOS_API_BASE / HIVEOS_WATCHER_USER / HIVEOS_WATCHER_PASS.
Runs until Ctrl+C. A .hiveos-seen.json next to the folder remembers hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import httpx

SUPPORTED = {".pdf", ".docx", ".txt", ".md", ".csv"}
POLL_SECONDS = 10.0


def _seen_path(folder: Path) -> Path:
    return folder / ".hiveos-seen.json"


def _load_seen(folder: Path) -> dict[str, str]:
    path = _seen_path(folder)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_seen(folder: Path, seen: dict[str, str]) -> None:
    _seen_path(folder).write_text(json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _login(client: httpx.Client, base_url: str, username: str, password: str) -> str:
    response = client.post(
        base_url + "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    response.raise_for_status()
    payload = response.json()
    token = payload["data"]["session"]["token"]
    assert isinstance(token, str)
    return token


def _collect(folder: Path, seen: dict[str, str]) -> list[Path]:
    pending: list[Path] = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in SUPPORTED:
            continue
        key = str(path.relative_to(folder))
        digest = _hash(path)
        if seen.get(key) == digest:
            continue
        pending.append(path)
        seen[key] = digest
    return pending


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", required=True)
    parser.add_argument("--base-url", default=os.environ.get("HIVEOS_API_BASE", "http://localhost:8080"))
    parser.add_argument("--username", default=os.environ.get("HIVEOS_WATCHER_USER", ""))
    parser.add_argument("--password", default=os.environ.get("HIVEOS_WATCHER_PASS", ""))
    args = parser.parse_args()
    if not args.username or not args.password:
        print("!! --username/--password (or HIVEOS_WATCHER_USER/PASS) are required")
        return 2

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"!! folder does not exist: {folder}")
        return 2

    seen = _load_seen(folder)
    with httpx.Client(timeout=120.0) as client:
        token = _login(client, args.base_url, args.username, args.password)
        headers = {"Authorization": "Bearer " + token}
        print(f"[ok] watching {folder} -> {args.base_url}")
        while True:
            try:
                pending = _collect(folder, seen)
                if pending:
                    with_pending = [(p, _hash(p)) for p in pending]
                    response = client.post(
                        args.base_url + "/api/v1/knowledge/upload",
                        headers=headers,
                        files=[
                            ("files", (p.name, p.open("rb"), "application/octet-stream"))
                            for p, _ in with_pending
                        ],
                    )
                    if response.status_code == 200:
                        names = ", ".join(p.name for p, _ in with_pending)
                        print(f"[ok] uploaded: {names}")
                        _save_seen(folder, seen)
                    else:
                        print(f"!! upload failed: HTTP {response.status_code} — will retry")
                        for p, digest in with_pending:
                            key = str(p.relative_to(folder))
                            if seen.get(key) == digest:
                                del seen[key]
                else:
                    _save_seen(folder, seen)
            except httpx.HTTPError as error:
                print(f"!! network error: {error} — retrying")
            except OSError as error:
                print(f"!! fs error: {error}")
            time.sleep(POLL_SECONDS)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[ok] watcher stopped")
        sys.exit(0)
