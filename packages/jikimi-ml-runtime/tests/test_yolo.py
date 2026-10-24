import numpy as np
from jikimi_ml_runtime.yolo import decode, letterbox, nms, to_normalized, to_tensor


def test_nms_suppresses_overlaps() -> None:
    boxes = np.array([[0, 0, 10, 10], [1, 1, 10, 10], [20, 20, 30, 30]], dtype=np.float32)
    scores = np.array([0.9, 0.8, 0.7], dtype=np.float32)
    assert nms(boxes, scores, 0.5).tolist() == [0, 2]


def test_decode_yolo11_layout() -> None:
    n, nc = 100, 80
    out = np.zeros((1, 4 + nc, n), dtype=np.float32)
    out[0, :4, 0] = [320, 320, 100, 50]  # cx, cy, w, h
    out[0, 4 + 3, 0] = 0.9  # motorcycle
    out[0, :4, 1] = [322, 321, 100, 50]  # duplicate, lower score
    out[0, 4 + 3, 1] = 0.6
    rows = decode(out, conf_thres=0.25, iou_thres=0.45)
    assert rows.shape == (1, 6)
    assert rows[0, 5] == 3 and abs(rows[0, 0] - 270) < 1e-3


def test_decode_yolo26_end_to_end_layout() -> None:
    out = np.zeros((1, 300, 6), dtype=np.float32)
    out[0, 0] = [10, 10, 50, 60, 0.8, 0]
    out[0, 1] = [100, 100, 150, 160, 0.1, 3]
    rows = decode(out, conf_thres=0.25)
    assert rows.shape == (1, 6) and rows[0, 4] == np.float32(0.8)


def test_letterbox_roundtrip() -> None:
    img = np.zeros((360, 640, 3), dtype=np.uint8)
    padded, lb = letterbox(img, 640)
    assert padded.shape == (640, 640, 3)
    assert to_tensor(padded).shape == (1, 3, 640, 640)
    # a box covering the full original frame maps back to (0, 0, 1, 1)
    top = lb.pad[1]
    rows = np.array([[0, top, 640, top + 360, 0.9, 0]], dtype=np.float32)
    norm = to_normalized(rows, lb)
    assert np.allclose(norm[0, :4], [0, 0, 1, 1], atol=1e-3)
