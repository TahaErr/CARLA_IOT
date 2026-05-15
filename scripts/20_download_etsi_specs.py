"""Download ETSI ASN.1 specifications needed by Sprint 3 module 1 (CPM encoder).

Pulls two GitLab archive zips from forge.etsi.org:

  - cpm_ts103324  @ v2.1.1   — ETSI TS 103 324 v2.1.1 (CPM Release 2)
  - cdd_ts102894_2 @ v2.2.1  — ETSI TS 102 894-2 (Common Data Dictionary,
                                CPM's only ASN.1 import dependency)

Tag choices:
  - CPM:  v2.1.1 is the version cited in the proposal (proposal §2.3, §9).
  - CDD:  the cdd_ts102894_2 README recommends v2.2.1 "for development";
          it's the matching CDD release for CPM v2.1.1.

Default extract location is `specs/cpm/` (per SPRINT3_HANDOFF.md §5). The
.asn files inside are tracked in git — this script is a one-shot bootstrap
for fresh checkouts that don't already have them.

Idempotent: skips download if the target directory already contains .asn
files. Pass --force to re-download.

Run:
    python scripts\\20_download_etsi_specs.py
    python scripts\\20_download_etsi_specs.py --force         # re-download
    python scripts\\20_download_etsi_specs.py --insecure      # if SSL fails
"""
from __future__ import annotations

import argparse
import os
import shutil
import ssl
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass


# Pinned tags; bump these here if/when ETSI publishes a newer release.
@dataclass(frozen=True)
class Spec:
    repo: str        # GitLab repo path under forge.etsi.org/rep/ITS/asn1/
    tag: str         # Git tag to download
    target: str      # Directory name under --out

SPECS = (
    Spec(repo="cpm_ts103324",   tag="v2.1.1", target="cpm_ts103324"),
    Spec(repo="cdd_ts102894_2", tag="V2.2.1", target="cdd_ts102894_2"),
)

BASE = "https://forge.etsi.org/rep/ITS/asn1"


def archive_url(spec: Spec) -> str:
    # GitLab archive URL pattern. The repeated "{repo}-{tag}" in the path is
    # the GitLab convention for the zip filename.
    return f"{BASE}/{spec.repo}/-/archive/{spec.tag}/{spec.repo}-{spec.tag}.zip"


def has_asn_files(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    for root, _dirs, files in os.walk(path):
        if any(f.lower().endswith(".asn") for f in files):
            return True
    return False


def download(url: str, dest: str, insecure: bool) -> None:
    ctx = ssl._create_unverified_context() if insecure else None
    print(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "v2xsim-spec-fetch/1"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    size_kb = os.path.getsize(dest) / 1024.0
    print(f"  wrote {dest} ({size_kb:.1f} KB)")


def extract_into(zip_path: str, target_dir: str) -> int:
    """Extract zip into target_dir, flattening the top-level "repo-tag/" prefix.
    Returns the number of .asn files extracted.
    """
    os.makedirs(target_dir, exist_ok=True)
    n_asn = 0
    with zipfile.ZipFile(zip_path) as zf:
        # All entries start with "<repo>-<tag>/..."; strip that first segment.
        top_level = None
        for info in zf.infolist():
            if info.is_dir():
                continue
            parts = info.filename.split("/", 1)
            if top_level is None:
                top_level = parts[0]
            rel = parts[1] if len(parts) == 2 else parts[0]
            if not rel:
                continue
            out_path = os.path.join(target_dir, rel)
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            with zf.open(info) as src, open(out_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if rel.lower().endswith(".asn"):
                n_asn += 1
    return n_asn


def fetch_spec(spec: Spec, out_dir: str, force: bool, insecure: bool) -> int:
    target_dir = os.path.join(out_dir, spec.target)

    if has_asn_files(target_dir) and not force:
        print(f"[skip] {spec.repo} {spec.tag} — already present at {target_dir}")
        return 0

    if os.path.isdir(target_dir) and force:
        print(f"[clean] removing existing {target_dir}")
        shutil.rmtree(target_dir)

    print(f"[fetch] {spec.repo} {spec.tag}")
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        zip_path = tmp.name
    try:
        download(archive_url(spec), zip_path, insecure=insecure)
        n_asn = extract_into(zip_path, target_dir)
        print(f"  extracted {n_asn} .asn file(s) into {target_dir}")
        return n_asn
    finally:
        try:
            os.unlink(zip_path)
        except OSError:
            pass


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=os.path.join("specs", "cpm"),
                   help="output directory (default: specs/cpm)")
    p.add_argument("--force", action="store_true",
                   help="re-download even if target dir already has .asn files")
    p.add_argument("--insecure", action="store_true",
                   help="skip TLS certificate verification (forge.etsi.org cert "
                        "chain has had issues on some Windows boxes)")
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)
    print(f"target: {os.path.abspath(args.out)}")

    total_asn = 0
    failures: list[str] = []
    for spec in SPECS:
        try:
            total_asn += fetch_spec(spec, args.out, args.force, args.insecure)
        except Exception as e:
            failures.append(f"{spec.repo} {spec.tag}: {e}")
            print(f"FAIL — {spec.repo} {spec.tag}: {e}", file=sys.stderr)

    print()
    if failures:
        print(f"FAIL — {len(failures)} spec(s) failed to download:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        print("Hint: if this is a TLS error on Windows, retry with --insecure.",
              file=sys.stderr)
        return 1

    print(f"OK — {total_asn} .asn file(s) total under {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
