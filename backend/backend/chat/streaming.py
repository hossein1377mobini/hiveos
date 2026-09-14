"""In-process SSE streaming hub (US-0902, T-S3-2).

ADR-023: single worker — the hub lives in the API process. Stream
lifecycle is audited via the normal audit trail (US-339) instead of
dedicated StreamSession/StreamChunk tables; persistence of those tables
is deferred (open question in the T-S3-2 report).
"""

import asyncio
import time
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

    _MAX_STREAMS = 200  # S12: cap concurrent tracked streams
    _MAX_BUFFERED_CHUNKS = 10_000  # S12: cap replay buffer per stream
    # E: a chunk count alone is not a memory bound - 10k chunks of any size grew
    # the buffer without limit. This caps the buffered text per stream.
    _MAX_BUFFERED_CHARS = 1_000_000

    def __init__(self) -> None:
        self._streams: dict[str, dict] = {}

    def reset(self) -> None:
        self._streams.clear()

    def _buffer(self, state: dict, text: str) -> None:
        """Append to the replay buffer while it stays inside both caps."""
        if len(state["chunks"]) >= self._MAX_BUFFERED_CHUNKS:
            return
        if state.get("buffered_chars", 0) + len(text) > self._MAX_BUFFERED_CHARS:
            return
        state["chunks"].append(text)
        state["buffered_chars"] = state.get("buffered_chars", 0) + len(text)

    def create(self, chat_session_id: uuid.UUID) -> str:
        self._sweep_expired()
        if len(self._streams) >= self._MAX_STREAMS:
            raise ApiError(503, "STREAM_LIMIT", "Too many active streams - try again shortly.")
        stream_id = str(uuid.uuid4())
        self._streams[stream_id] = {
            "session_id": chat_session_id,
            "queue": asyncio.Queue(),
            "chunks": [],
            "buffered_chars": 0,
            "status": STATUS_ACTIVE,
            "created_at": time.monotonic(),
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
            self._buffer(state, text)
            return len(state["chunks"]) - 1
        self._buffer(state, text)
        state["queue"].put_nowait(
            _event("stream.chunk", {"index": len(state["chunks"]) - 1, "text": text})
        )
        return len(state["chunks"]) - 1

    def complete(self, stream_id: str) -> str:
        """US-09.2.3: close the stream successfully; returns the full text."""
        state = self._get(stream_id)
        state["status"] = STATUS_COMPLETED
        state["queue"].put_nowait(_event("stream.completed", {"total_chunks": len(state["chunks"])}))
        # NOTE: the buffer must survive complete() - the SSE generator reads
        # buffered_chunks() to persist the assistant reply, and the TTL sweep
        # (plus the char cap above) is what bounds the memory, not this call.
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

    _STREAM_TTL_SECONDS = 600.0  # S12: reap unconsumed/finished streams

    def _sweep_expired(self) -> None:
        """S12 (external review): drop streams nobody consumed within TTL."""
        now = time.monotonic()
        # E: an ACTIVE stream may still be attached to a live SSE consumer;
        # reaping it made buffered_chunks() raise inside the router generator,
        # so the assistant reply was never persisted and the client saw nothing.
        expired = [
            sid
            for sid, st in self._streams.items()
            if st.get("status") != STATUS_ACTIVE
            and now - st.get("created_at", now) > self._STREAM_TTL_SECONDS
        ]
        for sid in expired:
            self._streams.pop(sid, None)

    def status(self, stream_id: str) -> str:
        return self._get(stream_id)["status"]

    def snapshot(self, stream_id: str) -> dict:
        """B7: full state (session binding included) for the router check."""
        return dict(self._get(stream_id))

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
