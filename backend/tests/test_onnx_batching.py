"""Regression: ONNX batching must survive batches of differing padded length.

Padding is computed per batch, so batching 8 short chunks after 2 long ones
produces (n, 233, h) and (n, 248, h). Concatenating those directly raised
"all the input array dimensions except for the concatenation axis must match
exactly", which surfaced to the PO as EMBEDDING_UNAVAILABLE on a real PDF and
failed the whole document even though the model was loaded and working.
"""

import numpy as np

from backend.knowledge import onnx_runtime


class _FakeSession:
    """Mimics the two graphs' real output shapes.

    The embedder returns (batch, seq_len, hidden) - width driven by the batch's
    padded length, which is what used to break concatenation. The reranker
    returns (batch, 1), a scalar score per pair, exactly like the real export.
    """

    def __init__(self, mode: str = "embed"):
        self.mode = mode
        self.seen: list[int] = []

    def get_inputs(self):
        class _Input:
            name = "input_ids"

        return [_Input()]

    def run(self, _outputs, feed):
        length = int(np.asarray(feed["input_ids"]).shape[1])
        self.seen.append(length)
        rows = int(np.asarray(feed["input_ids"]).shape[0])
        if self.mode == "score":
            return [np.ones((rows, 1), dtype=np.float32)]
        # (batch, seq_len, hidden) - exactly the shape that used to break.
        return [np.ones((rows, length, 4), dtype=np.float32)]


class _FakeTokenizer:
    """Pads to a length derived from the text, so batches differ."""

    def __call__(self, texts, texts_b=None, **kwargs):
        # The reranker calls the tokenizer as tokenizer(queries, documents),
        # so the pair form passes two positional arguments.
        if isinstance(texts, list) and texts and isinstance(texts[0], list):
            texts = [item[0] for item in texts]
        if texts_b is not None:
            texts = list(texts)
        # Pad to the longest row *in this batch*, exactly like a real
        # tokenizer with padding=True. A batch of short rows therefore gets a
        # narrower tensor than a batch of long ones.
        lengths = [max(1, len(str(t))) for t in texts]
        padded = max(lengths) + 200
        return {"input_ids": np.ones((len(texts), padded), dtype=np.int64)}


def _install(monkeypatch, mode: str = "embed"):
    session = _FakeSession(mode)
    monkeypatch.setattr(
        onnx_runtime, "_load", lambda _dir: (session, _FakeTokenizer())
    )
    return session


def test_embedding_survives_batches_of_different_padded_length(monkeypatch):
    session = _install(monkeypatch)
    texts = ["x" * n for n in range(1, 7)]
    vectors = onnx_runtime._embed_sync("/tmp/model", texts, max_length=512, batch_size=2)

    assert len(vectors) == len(texts)
    assert all(len(vector) == 4 for vector in vectors)
    # Three batches of two, and their padded widths really did differ -
    # otherwise this test would pass without exercising the bug.
    assert len(session.seen) == 3
    assert len(set(session.seen)) > 1, session.seen


def test_scores_survive_batches_of_different_padded_length(monkeypatch):
    _install(monkeypatch, mode="score")
    pairs = [["q", "d" * n] for n in range(1, 6)]
    scores = onnx_runtime._score_sync("/tmp/model", pairs, max_length=512, batch_size=2)
    assert len(scores) == len(pairs)


def test_empty_input_returns_nothing(monkeypatch):
    """The worker can legitimately call with no chunks; numpy.concatenate([])
    raises, so an empty batch must be handled rather than crash the job."""
    _install(monkeypatch)
    assert onnx_runtime._embed_sync("/tmp/model", [], max_length=512, batch_size=8) == []
