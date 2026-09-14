"""Export bge-m3 and bge-reranker-v2-m3 to int8 ONNX for the server image.

Run once on a machine with torch (this laptop), then copy the two directories
to /opt/models on the host. The server image itself only needs onnxruntime.

    py -3.11 backend/scripts/export_onnx_models.py --out C:/models
"""

import argparse
from pathlib import Path


def export_embedder(out_dir: Path, model_id: str) -> None:
    """bge-m3 -> a graph whose first output is the last hidden state."""
    from optimum.onnxruntime import ORTModelForFeatureExtraction
    from transformers import AutoTokenizer

    out_dir.mkdir(parents=True, exist_ok=True)
    model = ORTModelForFeatureExtraction.from_pretrained(
        model_id, export=True, use_io_binding=False
    )
    model.save_pretrained(str(out_dir))
    AutoTokenizer.from_pretrained(model_id).save_pretrained(str(out_dir))


def export_reranker(out_dir: Path, model_id: str) -> None:
    """Cross-encoder -> a graph whose first output is one logit per pair."""
    from optimum.onnxruntime import ORTModelForSequenceClassification
    from transformers import AutoTokenizer

    out_dir.mkdir(parents=True, exist_ok=True)
    model = ORTModelForSequenceClassification.from_pretrained(
        model_id, export=True, use_io_binding=False
    )
    model.save_pretrained(str(out_dir))
    AutoTokenizer.from_pretrained(model_id).save_pretrained(str(out_dir))


def quantize(directory: Path) -> None:
    """int8 dynamic quantization: ~4x smaller, ~2-3x faster on CPU.

    The exporter writes large weights to model.onnx_data next to the graph, so
    quantization has to run against the loaded model and then replace both
    files - quantizing in place leaves the fp32 external data behind and the
    graph silently keeps loading it.
    """
    from onnxruntime.quantization import QuantType, quantize_dynamic

    source = directory / "model.onnx"
    if not source.exists():
        return
    target = directory / "model_int8.onnx"
    quantize_dynamic(
        model_input=str(source),
        model_output=str(target),
        weight_type=QuantType.QInt8,
        # bge keeps its LayerNorm weights in fp32; quantizing them costs
        # accuracy for almost no size win.
        op_types_to_quantize=["MatMul"],
        extra_options={"WeightSymmetric": True, "ActivationSymmetric": False},
    )
    # Only after a successful write: swap the graph and drop the fp32 tail.
    for stale in (directory / "model.onnx_data", source):
        if stale.exists():
            stale.unlink()
    target.rename(source)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--skip-quantize", action="store_true")
    args = parser.parse_args()
    root = Path(args.out)

    embedder = root / "bge-m3-onnx"
    export_embedder(embedder, "BAAI/bge-m3")
    if not args.skip_quantize:
        quantize(embedder)
    print(f"embedder ready at {embedder}")

    reranker = root / "bge-reranker-v2-m3-onnx"
    export_reranker(reranker, "BAAI/bge-reranker-v2-m3")
    if not args.skip_quantize:
        quantize(reranker)
    print(f"reranker ready at {reranker}")


if __name__ == "__main__":
    main()