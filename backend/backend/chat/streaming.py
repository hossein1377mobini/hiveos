"""In-process SSE streaming hub (US-0902, T-S3-2).

ADR-023: single worker — the hub lives in the API process. Stream
lifecycle is audited via the normal audit trail (US-339) instead of
dedicated StreamSession/StreamChunk tables; persistence of those tables
is deferred (open question in the T-S3-2 report).
"""

import asyncio
import uuid

from backend.api_errors import ApiError

STREAM_TIMEOUT_SECONDS = 3600.0  # US-09.2.4 default; config-tunable later

STATUS_ACTIVE = "ACTIVE"
STATUS_COMPLETED = "COMPLETED"
STATUS_CLOSED = "CLOSED"
STATUS_FAILED = "FAILED"


def _event(kind: str, payload: dict) -> dict:
    return {"type": kind, "data": payload}


class StreamHub:
    """Registry of active SSE streams keyed by stream_id."""

    def __init__(self) -> None:
        self._streams: dict[str, dict] = {}

    def reset(self) -> None:
        self._streams.clear()

    def create(self, chat_session_id: uuid.UUID) -> str:
        stream_id = str(uuid.uuid4())
        self._streams[stream_id] = {
            "session_id": chat_session_id,
            "queue": asyncio.Queue(),
            "chunks": [],
            "status": STATUS_ACTIVE,
        }
        self._streams[stream_id]["queue"].put_nowait(
            _event("stream.started", {"stream_id": stream_id})
        )
        return stream_id

    def _get(self, stream_id: str) -> dict:
        state = self._streams.get(stream_id)
        if state is None:
            raise ApiError(404, "STREAM_NOT_FOUND", "Stream not found.")
        return state

    def emit_chunk(self, stream_id: str, text: str) -> int:
        """US-09.2.2: record + enqueue one content chunk; returns its index."""
        state = self._get(stream_id)
        if state["status"] != STATUS_ACTIVE:
            # US-09.2.2: chunks on a closed stream are buffered (replay later).
            state["chunks"].append(text)
            return len(state["chunks"]) - 1
        state["chunks"].append(text)
        state["queue"].put_nowait(
            _event("stream.chunk", {"index": len(state["chunks"]) - 1, "text": text})
        )
        return len(state["chunks"]) - 1

    def complete(self, stream_id: str) -> str:
        """US-09.2.3: close the stream successfully; returns the full text."""
        state = self._get(stream_id)
        state["status"] = STATUS_COMPLETED
        state["queue"].put_nowait(_event("stream.completed", {"total_chunks": len(state["chunks"])}))
        return "".join(state["chunks"])

    def fail(self, stream_id: str, message: str) -> None:
        state = self._get(stream_id)
        state["status"] = STATUS_FAILED
        state["queue"].put_nowait(_event("stream.error", {"message": message}))

    def close(self, stream_id: str) -> None:
        """Client disconnected: CLOSED; buffered chunks are kept for replay."""
        state = self._get(stream_id)
        if state["status"] == STATUS_ACTIVE:
            state["status"] = STATUS_CLOSED
            state["queue"].put_nowait(_event("stream.closed", {"reason": "client_disconnected"}))

    def status(self, stream_id: str) -> str:
        return self._get(stream_id)["status"]

    def buffered_chunks(self, stream_id: str) -> list[str]:
        return list(self._get(stream_id)["chunks"])

    async def events(self, stream_id: str, timeout: float = STREAM_TIMEOUT_SECONDS):
        """Yield SSE event payloads until completed/error/closed, then stop."""
        state = self._get(stream_id)
        while True:
            try:
                event = await asyncio.wait_for(state["queue"].get(), timeout=timeout)
            except TimeoutError:
                state["status"] = STATUS_CLOSED
                yield _event("stream.error", {"message": "timeout"})
                return
            kind = event["type"]
            yield event
            if kind in ("stream.completed", "stream.error", "stream.closed"):
                return


hub = StreamHub()


def sse_lines(event: dict) -> str:
    """Format one event as an SSE frame (US-0902 suggested format)."""
    import json

    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
