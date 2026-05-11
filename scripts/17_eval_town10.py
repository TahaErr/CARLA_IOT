"""Sprint 2 step 3 — cross-town evaluation of the fine-tuned YOLO26 detector.

Loads runs/detect/yolo26s_carla_town05/weights/best.pt (or whatever --weights
points at) and validates against dataset_town10/data.yaml. The Town10 dataset
should have been generated with `--val-stride 1` so all frames go to the val
split — this script then evaluates against that "val" set, which is in fact
the held-out cross-town test set.

This implements proposal §4.6 metric: "RSU detector precision/recall measured
on the held-out Town10 map (cross-town generalisation)".

Outputs:
  - mAP@50, mAP@50:95, precision, recall (overall + per-class)
  - confusion matrix and PR curves auto-saved by Ultralytics under
    runs/detect/<name>/

PASS criterion: script completes without error; metrics printed.
A QUALITY criterion (separate question): mAP@50 should be close to the
Town05 val number from script 16. A large gap → significant cross-town
generalisation gap, which is itself a finding for the report.
"""
from __future__ import annotations

import argparse
import os
import sys


def main(args) -> int:
    if not os.path.exists(args.weights):
        print(f"FAIL — weights not found: {args.weights}", file=sys.stderr)
        print("Did you run scripts/16_train_yolo.py first?", file=sys.stderr)
        return 1
    if not os.path.exists(args.data):
        print(f"FAIL — data.yaml not found: {args.data}", file=sys.stderr)
        print("Generate the Town10 test set with:", file=sys.stderr)
        print("  python scripts/15_generate_dataset.py --map Town10 \\",
              file=sys.stderr)
        print("    --out ./dataset_town10 --val-stride 1", file=sys.stderr)
        return 1

    import torch
    from ultralytics import YOLO

    if torch.cuda.is_available():
        device = 0
        print(f"device: cuda:0 ({torch.cuda.get_device_name(0)})")
    else:
        device = "cpu"

    print(f"loading weights: {args.weights}")
    model = YOLO(args.weights)

    print(f"evaluating on {args.data} (Town10 cross-town test set)...")
    val_kwargs = dict(
        data=args.data,
        imgsz=args.imgsz,
        batch=args.batch,
        device=device,
        split="val",
        name=args.name,
        plots=True,
        verbose=False,
    )
    if args.project is not None:
        val_kwargs["project"] = args.project
    metrics = model.val(**val_kwargs)

    print()
    print("=== Town10 cross-town evaluation ===")
    try:
        print(f"  mAP@50      : {metrics.box.map50:.4f}")
        print(f"  mAP@50:95   : {metrics.box.map:.4f}")
        print(f"  precision   : {metrics.box.mp:.4f}")
        print(f"  recall      : {metrics.box.mr:.4f}")
        names = metrics.names if hasattr(metrics, "names") else model.names
        if hasattr(metrics.box, "ap_class_index"):
            print()
            print("  per-class precision / recall / mAP50 / mAP50:95:")
            for i, ci in enumerate(metrics.box.ap_class_index):
                ci = int(ci)
                cname = names[ci] if isinstance(names, dict) else names[ci]
                p = metrics.box.p[i] if i < len(metrics.box.p) else float("nan")
                r = metrics.box.r[i] if i < len(metrics.box.r) else float("nan")
                ap50 = metrics.box.ap50[i] if i < len(metrics.box.ap50) else float("nan")
                ap = metrics.box.ap[i] if i < len(metrics.box.ap) else float("nan")
                print(f"    {ci} {cname:12s}  P={p:.3f}  R={r:.3f}  "
                      f"mAP50={ap50:.4f}  mAP={ap:.4f}")
    except Exception as e:
        print(f"  (could not parse metrics object: {e})")

    try:
        out_dir = str(metrics.save_dir)
    except Exception:
        out_dir = f"{args.project or 'runs/detect'}/{args.name}"
    print()
    print(f"plots + confusion matrix saved under: {out_dir}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "--weights",
        default="runs/detect/yolo26s_carla_town05/weights/best.pt",
        help="fine-tuned weights from scripts/16_train_yolo.py",
    )
    p.add_argument("--data", default="./dataset_town10/data.yaml",
                   help="Town10 dataset yaml (generated with --val-stride 1)")
    p.add_argument("--imgsz", type=int, default=1280,
                   help="must match the imgsz the model was trained at; "
                        "default 1280 to match scripts/16_train_yolo.py")
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--project", default=None,
                   help="override Ultralytics save directory. Default None "
                        "lets Ultralytics use 'runs/detect/' (recommended).")
    p.add_argument("--name", default="yolo26s_carla_town10_eval")
    args = p.parse_args()
    sys.exit(main(args))
