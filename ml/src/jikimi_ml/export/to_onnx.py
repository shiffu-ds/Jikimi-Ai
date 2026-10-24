"""Export trained models for the torch-free edge runtime (ONNX -> optionally OpenVINO IR)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def export(model: Any, path: str | Path, opset: int = 17) -> Path:
    """ST-GCN -> ONNX with input ``poses`` (1, 3, 32, 17, 2) and output ``logit``."""
    import torch

    model.eval()
    dummy = torch.zeros(1, 3, 32, 17, 2)
    out = Path(path)
    torch.onnx.export(
        model,
        (dummy,),
        str(out),
        input_names=["poses"],
        output_names=["logit"],
        dynamic_axes={"poses": {0: "batch"}, "logit": {0: "batch"}},
        opset_version=opset,
        dynamo=False,
    )
    return out


def to_openvino(onnx_path: str | Path, out_dir: str | Path) -> Path:
    """Optional: ONNX -> OpenVINO IR (FP16) for Intel CPUs/iGPUs."""
    import openvino as ov

    model = ov.convert_model(str(onnx_path))
    out = Path(out_dir) / (Path(onnx_path).stem + ".xml")
    ov.save_model(model, str(out), compress_to_fp16=True)
    return out
