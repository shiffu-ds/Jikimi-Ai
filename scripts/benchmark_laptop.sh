#!/usr/bin/env bash
# Laptop / edge benchmark (plan Section 7.8). Writes eval/reports/bench-<host>.json
set -euo pipefail
mkdir -p eval/reports
OUT="eval/reports/bench-$(hostname).json"
echo "== pipeline throughput (simulator, 2 cameras worth of frames) =="
uv run python -m eval.load.multi_stream --seconds 60 --report "$OUT"
if [ -f models/yolo11n_int8_openvino_model/yolo11n.xml ] && command -v benchmark_app >/dev/null; then
  echo "== OpenVINO YOLO11n INT8 =="
  benchmark_app -m models/yolo11n_int8_openvino_model/yolo11n.xml -d CPU -hint latency -t 20
fi
if [ -f models/yolo26n_int8_openvino_model/yolo26n.xml ] && command -v benchmark_app >/dev/null; then
  echo "== OpenVINO YOLO26n INT8 (NMS-free) =="
  benchmark_app -m models/yolo26n_int8_openvino_model/yolo26n.xml -d CPU -hint latency -t 20
fi
echo "report: $OUT"
