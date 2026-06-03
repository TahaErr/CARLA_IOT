"""fix_cav_distance_fallback.py

Idempotent patcher for v2xsim/cav.py, same find/replace style as the
repo's apply_patches.py.

THE BUG it fixes
----------------
Three constants are mutually inconsistent:
  - ego self-ghost filter excludes a track only if it is < 2.5 m AND co-moving
  - the distance-based safety fallback fires HARD_BRAKE for any confirmed
    in-lane track within d_long <= 4.0 m, WITHOUT checking relative velocity
  - AI_REALISTIC follows its leader at a 3.0 m gap

So a normally-followed leader sits in the dead zone (2.5 m < 3.0 m < 4.0 m):
not excluded as a self-ghost, inside the 4 m hard-brake band, and since the
fallback ignores closing speed, the CAV slams brake=1.0 on a co-moving leader
it is safely following. The follower 3 m back cannot stop -> CAV-CAV rear-end.
This is worst at p=1.0 (every leader is a CAV), which is why p=1.0 collisions
exceed p=0.9 and are entirely CAV-CAV.

THE FIX
-------
Add a longitudinal closing-rate gate: only apply the distance fallback when
the gap is actually shrinking (ego closing on the track). A co-moving leader
has closing ~0 and is skipped; a stationary wreck (ego rolling toward it) and
a genuinely slowing/cutting-in vehicle still have closing > 0 and trigger.
Preserves the two existing wreck tests; does NOT reintroduce the v1
under-braking (normal car-following stays the TM's job).

    python fix_cav_distance_fallback.py path/to/v2xsim/cav.py
"""
from __future__ import annotations

import sys


# (label, idempotency_marker, OLD, NEW)
PATCH_CAV_EDITS = [
    (
        "C1 closing-rate gate on distance-based safety fallback",
        "closing_ms",  # idempotency marker
        # OLD: the lateral-offset line + the fallback guard (16-space indent).
        "                d_lat = abs(-dx * hy + dy * hx)\n"
        "                if d_long > 0.0 and d_lat <= self.brake_warning_lateral_m:",
        # NEW: compute longitudinal closing speed and require the gap to be
        #      shrinking before the emergency fallback can fire.
        "                d_lat = abs(-dx * hy + dy * hx)\n"
        "                # Longitudinal closing speed (>0 = gap shrinking). A\n"
        "                # co-moving leader we are safely following has closing\n"
        "                # ~0 and must NOT trip the emergency fallback, else a\n"
        "                # CAV hard-brakes on the car ahead at its own 3 m gap\n"
        "                # (which sits inside the 4 m band). Only stationary\n"
        "                # wrecks / genuinely closing hazards qualify.\n"
        "                rel_vx = track.vx_ms - ego_vx_ms\n"
        "                rel_vy = track.vy_ms - ego_vy_ms\n"
        "                closing_ms = -(rel_vx * hx + rel_vy * hy)\n"
        "                if (d_long > 0.0 and d_lat <= self.brake_warning_lateral_m\n"
        "                        and closing_ms >= 0.5):",
    ),
]


def apply(path: str) -> int:
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    changed = False
    missing = []
    for label, marker, old, new in PATCH_CAV_EDITS:
        if marker in src:
            print(f"  [skip]    {label} (already applied)")
            continue
        if old in src:
            src = src.replace(old, new, 1)
            changed = True
            print(f"  [applied] {label}")
        else:
            missing.append(label)
            print(f"  [MISSING] {label} — OLD anchor not found; apply by hand")

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
        print(f"  -> wrote {path}")
    else:
        print(f"  -> {path} unchanged")

    if missing:
        print(f"\n{len(missing)} edit(s) need manual application: {', '.join(missing)}")
        return 2
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python fix_cav_distance_fallback.py path/to/v2xsim/cav.py",
              file=sys.stderr)
        sys.exit(1)
    sys.exit(apply(sys.argv[1]))
