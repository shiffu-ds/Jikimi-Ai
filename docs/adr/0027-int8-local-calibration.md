# ADR-0027: INT8 models are quantized with NNCF on local frames, without PyTorch

- **Status:** accepted (new in v2.4)
- **Date:** 2026-10-24
- **Feature / gap:** F19 (edge cost), plan Section 7.8; results in `docs/results.md` ("OpenVINO INT8")

## Context
Ultralytics' `format=openvino int8=True` export needs PyTorch (and pulled a CUDA build of it,
gigabytes) and downloads COCO images for calibration. Calibration images should look like the
site's cameras, and the comparison with FP32 should be measured, not assumed.

## Decision
`scripts/quantize_openvino.py` converts the ONNX models with OpenVINO and quantizes them with
NNCF (mixed preset), calibrated on frames from local footage plus simulator scenes, keeping the
YOLO head's box / keypoint decoding in floating point. It validates on other frames against the
FP32 model (matched boxes, keypoint shift) and times onnxruntime FP32, OpenVINO FP32 and INT8.
openvino + nncf are export-time tools; the edge only needs openvino.

## Consequences
On the i5-6200U: detector 102 -> 76 ms, pose 158 -> 100 ms, models ~4x smaller, the pipeline 1.7x
faster (1.3 cameras at 5 fps). INT8 boxes agree with FP32 at recall 0.96 (pose 0.91, keypoints
0.8 px). On the junction clip INT8 produced one VERIFY snatch that FP32 did not, so a new model
or profile goes through shadow mode before live alerts. Re-quantize with each site's own frames
once the pilot has footage.
