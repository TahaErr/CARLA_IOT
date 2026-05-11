"""Sprint 2 step 3 — fine-tune YOLO26s on the Town05 CARLA dataset.

Reads dataset_town05/data.yaml (produced by 15_generate_dataset.py), runs
Ultralytics fine-tuning starting from yolo26s.pt (COCO-pretrained), and
saves the best weights under runs/detect/<name>/weights/best.pt.

Defaults are tuned for an RTX 5080 with the CUDA-12.8 torch build:
  - imgsz=1280: matches the dataset's native 1280x720 resolution. Letterboxing
    to YOLO's default 640 halves linear resolution and shrinks distant VRUs
    (pedestrians, cyclists) below ~15 px, which the network struggles with.
    YOLO26's small-target features (ProgLoss + STAL) only pay off at native
    resolution. This costs ~2x training time but is needed for the proposal's
    VRU detection claim.
  - batch=8: fits in 16 GB VRAM at imgsz=1280. Pass batch=-1 to let
    Ultralytics auto-pick.
  - epochs=50: Sprint 2 budget. First fine-tune; if mAP plateaus early
    the patience flag will short-circuit.

PASS criterion: training completes and runs/detect/<name>/weights/best.pt
exists, with mAP@50 reported in the final summary.
"""
from __future__ import annotations

import argparse
import os
import sys


def main(args) -> int:
    if not os.path.exists(args.data):
        print(f"FAIL — data.yaml not found: {args.data}", file=sys.stderr)
        print("Did you run scripts/15_generate_dataset.py first?", file=sys.stderr)
        return 1

    # Lazy-import so --help works without ultralytics/torch installed.
    import torch
    from ultralytics import YOLO

    if torch.cuda.is_available():
        device = 0
        print(f"device: cuda:0 ({torch.cuda.get_device_name(0)})")
    else:
        device = "cpu"
        print("device: cpu  (training will be slow — verify CUDA-12.8 torch build)")

    print(f"loading model: {args.model}")
    model = YOLO(args.model)

    print(f"training on {args.data} for {args.epochs} epochs at imgsz={args.imgsz}...")
    train_kwargs = dict(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=device,
        patience=args.patience,
        cache=args.cache,
        name=args.name,
        save=True,
        save_period=args.save_period,
        seed=args.seed,
        verbose=True,
    )
    # Only pass project if explicitly given — otherwise Ultralytics uses its
    # own default ('runs/detect'). Passing it explicitly causes a duplicate
    # 'runs/detect/runs/detect/...' nesting on some Ultralytics versions.
    if args.project is not None:
        train_kwargs["project"] = args.project
    model.train(**train_kwargs)

    # Run final validation on the val split and print the headline metrics.
    print()
    print("running final validation...")
    val_kwargs = dict(data=args.data, imgsz=args.imgsz, batch=args.batch,
                      device=device, name=f"{args.name}_val", verbose=False)
    if args.project is not None:
        val_kwargs["project"] = args.project
    metrics = model.val(**val_kwargs)

    print()
    print("=== final metrics on val split ===")
    # ultralytics stores per-class metrics in metrics.box; the .map / .map50 attrs
    # are the dataset-level mean over classes.
    try:
        print(f"  mAP@50      : {metrics.box.map50:.4f}")
        print(f"  mAP@50:95   : {metrics.box.map:.4f}")
        print(f"  precision   : {metrics.box.mp:.4f}")
        print(f"  recall      : {metrics.box.mr:.4f}")
        # per-class
        names = metrics.names if hasattr(metrics, "names") else model.names
        if hasattr(metrics.box, "ap_class_index"):
            print()
            print("  per-class mAP@50 / mAP@50:95:")
            for i, ci in enumerate(metrics.box.ap_class_index):
                cname = names[int(ci)] if isinstance(names, dict) else names[int(ci)]
                ap50 = metrics.box.ap50[i] if i < len(metrics.box.ap50) else float("nan")
                ap = metrics.box.ap[i] if i < len(metrics.box.ap) else float("nan")
                print(f"    {int(ci)} {cname:12s}  mAP50={ap50:.4f}  mAP={ap:.4f}")
    except Exception as e:
        print(f"  (could not parse metrics object: {e})")

    # Pull the actual save_dir from the trainer (handles default 'runs/detect/'
    # vs. user override). Falls back to a string guess if attribute missing.
    try:
        save_dir = str(model.trainer.save_dir)
    except Exception:
        save_dir = f"{args.project or 'runs/detect'}/{args.name}"
    print()
    print(f"weights at: {save_dir}/weights")
    print(f"  best.pt → use this for evaluation (scripts/17_eval_town10.py)")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="./dataset_town05/data.yaml",
                   help="YOLO data.yaml produced by scripts/15_generate_dataset.py")
    p.add_argument("--model", default="yolo26s.pt",
                   help="starting weights — yolo26{n,s,m,l,x}.pt")
    p.add_argument("--epochs", type=int, default=50)
    p.add_argument("--imgsz", type=int, default=1280)
    p.add_argument("--batch", type=int, default=8,
                   help="batch size; pass -1 to let Ultralytics auto-pick")
    p.add_argument("--patience", type=int, default=20,
                   help="early-stopping: stop if val mAP doesn't improve for N epochs")
    def _parse_cache(v):
        # Argparse passes strings; Ultralytics wants bool False or 'ram'/'disk'.
        if isinstance(v, bool):
            return v
        s = str(v).lower()
        if s in ("false", "none", "no", "0", "off"):
            return False
        return v  # 'ram' or 'disk'

    p.add_argument("--cache", default=False, type=_parse_cache,
                   help="image cache: False (default, no cache — safe and "
                        "Windows-friendly), 'disk' (cached as .npy, ~30 GB; "
                        "faster epochs after first), 'ram' (fastest on Linux, "
                        "may MemoryError on Windows multiprocessing).")
    p.add_argument("--project", default=None,
                   help="override Ultralytics save directory. Default None lets "
                        "Ultralytics use 'runs/detect/' (recommended); passing "
                        "this explicitly can produce duplicate path prefixes on "
                        "some versions.")
    p.add_argument("--name", default="yolo26s_carla_town05")
    p.add_argument("--save-period", type=int, default=10,
                   help="save a checkpoint every N epochs (in addition to best.pt)")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    sys.exit(main(args))
