"""Sprint 2 step 1 — YOLOv8s detection test on a single saved RSU frame.

Loads COCO-pretrained YOLOv8s, runs inference on one PNG, prints detected
classes + confidences, and saves the annotated image with bounding boxes.

Usage:
    python scripts\\13_yolo_test.py --in out\\rsu00.png
    python scripts\\13_yolo_test.py --in out\\some_frame.png --model yolov8n.pt
"""
from __future__ import annotations

import argparse
import os
import sys

import cv2
from ultralytics import YOLO


def main(in_path: str, out_path: str | None, model_name: str, conf_thresh: float) -> int:
    if not os.path.exists(in_path):
        print(f"FAIL — input file not found: {in_path}", file=sys.stderr)
        return 1

    print(f"loading model {model_name}...")
    model = YOLO(model_name)  # auto-downloads from ultralytics on first use
    print(f"  model has {len(model.names)} COCO classes")

    print(f"reading {in_path}...")
    img = cv2.imread(in_path)
    if img is None:
        print("FAIL — cv2.imread returned None", file=sys.stderr)
        return 1
    print(f"  image shape: {img.shape}")

    print("running inference...")
    results = model(img, conf=conf_thresh, verbose=False)[0]
    n = len(results.boxes)
    print(f"  {n} detection(s) at conf >= {conf_thresh}")

    for i, box in enumerate(results.boxes):
        cls_id = int(box.cls[0].item())
        conf = float(box.conf[0].item())
        name = results.names[cls_id]
        xyxy = [float(v) for v in box.xyxy[0].tolist()]
        print(
            f"  [{i:02d}] {name:14s}  conf={conf:.2f}  "
            f"bbox=[{xyxy[0]:.0f},{xyxy[1]:.0f},{xyxy[2]:.0f},{xyxy[3]:.0f}]"
        )

    annotated = results.plot()  # numpy BGR with boxes + labels drawn

    if out_path is None:
        base, ext = os.path.splitext(in_path)
        out_path = base + "_yolo" + ext
    cv2.imwrite(out_path, annotated)
    print(f"OK — wrote {out_path}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="in_path", required=True, help="input PNG path")
    p.add_argument("--out", default=None, help="output PNG (default: <in>_yolo.png)")
    p.add_argument(
        "--model",
        default="yolo26s.pt",
        help="yolo26n/s/m/l/x .pt — n=fastest, x=most accurate. yolo26 is the "
        "Sep-2025 release with NMS-free inference and ProgLoss/STAL for "
        "small-object accuracy (relevant for VRU detection).",
    )
    p.add_argument("--conf", type=float, default=0.25, help="confidence threshold")
    args = p.parse_args()
    sys.exit(main(args.in_path, args.out, args.model, args.conf))
