"""19_check_distribution.py — count YOLO labels per class in a dataset.

Quick diagnostic for class imbalance. Run after generating a dataset to see
how many instances of each class were actually labelled across train/val.

Usage:
    python scripts\\19_check_distribution.py .\\dataset_town05
"""
from __future__ import annotations

import argparse
import glob
import os
from collections import Counter


CLASS_NAMES = ["vehicle", "motorcycle", "bicycle", "pedestrian"]


def main(dataset_dir: str) -> int:
    if not os.path.isdir(dataset_dir):
        print(f"FAIL — not a directory: {dataset_dir}")
        return 1

    counts = {"train": Counter(), "val": Counter()}
    for split in ("train", "val"):
        labels_dir = os.path.join(dataset_dir, "labels", split)
        for lbl in glob.glob(os.path.join(labels_dir, "*.txt")):
            with open(lbl) as f:
                for line in f:
                    parts = line.split()
                    if not parts:
                        continue
                    cls = int(parts[0])
                    counts[split][cls] += 1

    # If train is empty across all classes, this is a test-set generation
    # (--val-stride 1) rather than a training dataset; report on val only.
    train_total = sum(counts["train"].values())
    test_set_mode = (train_total == 0) and (sum(counts["val"].values()) > 0)

    print(f"dataset: {dataset_dir}")
    if test_set_mode:
        print("  (test-set mode: train empty by design, evaluating val split only)")
    print()
    print(f"  {'cls':<3}{'name':<14}{'train':>10}{'val':>10}{'imbalance':>14}")
    print(f"  {'---':<3}{'----':<14}{'-----':>10}{'---':>10}{'---------':>14}")

    if test_set_mode:
        ref_max = max(counts["val"].values())
        for i, n in enumerate(CLASS_NAMES):
            v = counts["val"][i]
            ratio = ref_max / max(v, 1)
            flag = "  ← UNDER" if ratio > 4 and v > 0 else ("  ← MISSING" if v == 0 else "")
            print(f"  {i:<3}{n:<14}{0:>10}{v:>10}{ratio:>13.1f}x{flag}")
    else:
        train_max = max(counts["train"].values()) if counts["train"] else 1
        for i, n in enumerate(CLASS_NAMES):
            t, v = counts["train"][i], counts["val"][i]
            ratio = train_max / max(t, 1)
            flag = "  ← UNDER" if ratio > 4 and t > 0 else ("  ← MISSING" if t == 0 else "")
            print(f"  {i:<3}{n:<14}{t:>10}{v:>10}{ratio:>13.1f}x{flag}")

    print()
    print("  imbalance = (most-frequent class count) / (this class's count)")
    print("  >4x is generally problematic for YOLO; >8x severe.")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("dataset_dir", help="path to dataset (e.g. ./dataset_town05)")
    args = p.parse_args()
    raise SystemExit(main(args.dataset_dir))
