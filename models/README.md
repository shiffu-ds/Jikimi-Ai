# models/ (gitignored)

Model files never go into git (plan Section 7.19). Fill this folder with:

```bash
make models PROFILE=laptop      # = uv run python scripts/download_models.py --profile laptop
```

| File | What | How it is produced |
|---|---|---|
| `yolo11n_int8_openvino_model/` | COCO detector, OpenVINO INT8 | `uv run python scripts/quantize_openvino.py` (no PyTorch, see below) or `yolo export model=yolo11n.pt format=openvino int8=True imgsz=640` |
| `yolo26n_int8_openvino_model/` | YOLO26 nano (NMS-free) for `make bench` comparison | `yolo export model=yolo26n.pt format=openvino int8=True imgsz=640` |
| `yolo11n-pose_int8_openvino_model/` | pose for the snatch plugin | same script, or `yolo export model=yolo11n-pose.pt format=openvino int8=True` |
| `stgcn_paksnatch.onnx` | two-person ST-GCN | `python -m jikimi_ml.train.train_stgcn ...` (PakSnatch-sim pre-training, then real data) |
| `face_detection_yunet_2023mar.onnx` | optional face detector for blur | OpenCV Zoo (checksum pinned in the script) |

| `yolo11n.onnx`, `yolo11n-pose.onnx` | `onnx-cpu` profile (any CPU, onnxruntime) used by `eval.footage_check` | see below |
| `faster-whisper-small/` | Whisper small, CTranslate2 int8: guard voice replies (F12, server only) | see below |
| `trajectory_tf.onnx` (+ `.json` camera list) | cross-camera route model (F2 Tier 2), per site | `python -m jikimi_ml.train.train_trajectory` (synthetic routes; retrain on the site's own) |
| `zero_dce_pp.onnx` | low-light enhancer (F18, off by default) | `python -m jikimi_ml.train.train_lowlight` |
| `audio_events.onnx` (+ `.json` classes) | audio events (F13), only with recordings | `python -m jikimi_ml.train.train_audio --data data/audio` |
| `smolvlm-256m-instruct/` (+ `verifier.json`) | VLM verifier / distillation teacher (F5/F6, server) | HuggingFace `HuggingFaceTB/SmolVLM-256M-Instruct` (Apache-2.0, 513 MB), then `python -m eval.vlm_check` |

Ultralytics (and therefore PyTorch) is needed **only for exporting**, never on the edge.

**CPU-only export without pulling CUDA.** `uv run --with ultralytics ...` resolves `torchvision`
from PyPI, which drags in a CUDA build of torch (gigabytes). This repo's venv already has
`torch+cpu`, so install the exporter next to it without dependencies, export, and remove it:

```bash
uv pip install --python .venv/bin/python --no-deps --index https://download.pytorch.org/whl/cpu \
    --index-strategy unsafe-best-match "torchvision==0.29.1+cpu" ultralytics ultralytics-thop py-cpuinfo
cd models && ../.venv/bin/yolo export model=yolo11n.pt format=onnx imgsz=640 simplify=False opset=17
../.venv/bin/yolo export model=yolo11n-pose.pt format=onnx imgsz=640 simplify=False opset=17
cd .. && uv pip uninstall --python .venv/bin/python ultralytics ultralytics-thop py-cpuinfo torchvision
```

The weights (`yolo11n.pt`, `yolo11n-pose.pt`) come from the Ultralytics release assets
(AGPL-3.0: check the licence before shipping a product built on them).

**INT8 without PyTorch.** With the two ONNX files in place, `uv run python scripts/quantize_openvino.py`
quantizes both with NNCF (export-time: `uv pip install openvino nncf`), calibrated on frames from
the videos in `data/footage/` plus simulator scenes, and writes the `laptop` profile's folders and
`eval/reports/openvino_int8.json` (agreement with FP32, ms per inference). Put the site's own
footage in `data/footage/` first so calibration sees its cameras.

**Voice replies (F12, server only).** `uv sync --extra voice`, then the CTranslate2 conversion of
OpenAI's Whisper small (MIT licence, ~484 MB). Nothing is downloaded at run time: the server only
loads this folder, and without it `/v1/voice/reply` answers 503 and guards use the buttons.

```bash
mkdir -p models/faster-whisper-small
for f in config.json model.bin tokenizer.json vocabulary.txt; do
  curl -L -o models/faster-whisper-small/$f https://huggingface.co/Systran/faster-whisper-small/resolve/main/$f
done
```
