"""fix_ablation_realism_and_determinism.py

Idempotent patcher for scripts/40_ablation_run.py, in the same
find/replace style as the repo's existing apply_patches.py.

It applies four edits:

  E1  Import AGGRESSIVE_HOSTILE + DISTRACTED from v2xsim.hdv.
  E2  Determinism: seed the Traffic Manager AND the pedestrian-nav RNG
      from the cell seed (fixes the p=0 arms diverging — "Symptom A").
  E3  Restore the HDV avoidance-disable, but PROFILE-SELECTIVE: avoidance
      is removed from DISTRACTED + AGGRESSIVE_HOSTILE; ONLY ATTENTIVE keeps
      it and drives safely (fixes "Symptom B" + the realism problem). The
      distracted-vs-aggressive gradient is preserved by their ignore rates.
  E4  Fix the stale role-print that still claimed "avoidance OFF" for all HDVs.

IMPORTANT — I am working from project-knowledge fragments, not your
byte-exact file, so an OLD anchor may not match verbatim (whitespace,
comment text). This script does NOT silently skip a non-match: it prints
[MISSING] for any anchor it cannot find so you can fix it by hand. Run it,
read the per-edit log, and apply any [MISSING] edit manually.

    python fix_ablation_realism_and_determinism.py path/to/scripts/40_ablation_run.py
"""
from __future__ import annotations

import sys


# (label, idempotency_marker, OLD, NEW)
PATCH_40_EDITS = [
    # -----------------------------------------------------------------
    # E1. Import the two profile objects we need for the selective disable.
    # -----------------------------------------------------------------
    (
        "E1 import AGGRESSIVE_HOSTILE + DISTRACTED",
        "    AGGRESSIVE_HOSTILE,",  # idempotency marker
        "from v2xsim.hdv import (\n"
        "    AI_REALISTIC,\n"
        "    ATTENTIVE,\n"
        "    HOSTILE_MIX,\n"
        "    DEFAULT_MIX,\n"
        "    apply_mix_to_vehicles,\n"
        "    apply_profile_to_tm,\n"
        "    disable_collision_detection_for,\n"
        ")",
        "from v2xsim.hdv import (\n"
        "    AGGRESSIVE_HOSTILE,\n"
        "    AI_REALISTIC,\n"
        "    ATTENTIVE,\n"
        "    DISTRACTED,\n"
        "    HOSTILE_MIX,\n"
        "    DEFAULT_MIX,\n"
        "    apply_mix_to_vehicles,\n"
        "    apply_profile_to_tm,\n"
        "    disable_collision_detection_for,\n"
        ")",
    ),
    # -----------------------------------------------------------------
    # E2. Determinism seeds (Symptom A: p=0 arms must be identical).
    #     synchronous_mode() sets TM sync mode but does NOT seed it; the
    #     two sister scripts (15_generate_dataset.py, 18_survey_*) seed it
    #     themselves. The runner doesn't. Pedestrian nav locations come
    #     from get_random_location_from_navigation(), governed by
    #     set_pedestrians_seed() — also never called.
    #     NOTE: whitespace-sensitive anchor; verify the indentation of the
    #     first `world.tick()` after `with synchronous_mode(...)` in your file.
    # -----------------------------------------------------------------
    (
        "E2 seed TM + pedestrians",
        "tm.set_random_device_seed(seed)",  # idempotency marker
        "        with synchronous_mode(client, dt=args.dt) as (world, tm):\n"
        "            world.tick()",
        "        with synchronous_mode(client, dt=args.dt) as (world, tm):\n"
        "            # Determinism: seed the Traffic Manager and the\n"
        "            # pedestrian-nav RNG from the cell seed, so re-runs and\n"
        "            # the three arms at p=0 are reproducible. Mirrors\n"
        "            # 15_generate_dataset.py.\n"
        "            try:\n"
        "                tm.set_random_device_seed(seed)\n"
        "            except Exception:\n"
        "                pass\n"
        "            try:\n"
        "                world.set_pedestrians_seed(seed)  # get_random_location_from_navigation()\n"
        "            except Exception:\n"
        "                pass\n"
        "            world.tick()",
    ),
    # -----------------------------------------------------------------
    # E3. Restore avoidance-disable, PROFILE-SELECTIVE (Symptom B + realism).
    #     Anchor = the commented-out blanket call + its following world.tick().
    # -----------------------------------------------------------------
    (
        "E3 profile-selective avoidance disable",
        "RECKLESS_PROFILE_NAMES",  # idempotency marker
        "            # disable_collision_detection_for(tm, hdv_vehicles, vehicles)\n"
        "            world.tick()",
        "            # Remove TM avoidance (one-way) from the imperfect driver\n"
        "            # profiles. ONLY ATTENTIVE keeps avoidance and drives\n"
        "            # safely: disabling it for EVERY HDV made even attentive\n"
        "            # drivers crash (unrealistic), but keeping it ON for\n"
        "            # DISTRACTED made distracted == attentive (also wrong).\n"
        "            # With avoidance off, each profile's own ignore rate sets\n"
        "            # the gradient: distracted (20%) < aggressive-hostile (40%).\n"
        "            # Directional: reckless HDVs don't avoid; ATTENTIVE + CAVs do.\n"
        "            RECKLESS_PROFILE_NAMES = {AGGRESSIVE_HOSTILE.name, DISTRACTED.name}  # only ATTENTIVE keeps avoidance\n"
        "            reckless_hdvs = [\n"
        "                v for v in hdv_vehicles\n"
        "                if hdv_assignments.get(v.id) in RECKLESS_PROFILE_NAMES\n"
        "            ]\n"
        "            if reckless_hdvs:\n"
        "                disable_collision_detection_for(tm, reckless_hdvs, vehicles)\n"
        "            if not args.quiet:\n"
        "                print(f\"   avoidance OFF for {len(reckless_hdvs)} reckless HDV(s); \"\n"
        "                      f\"ON for {len(hdv_vehicles) - len(reckless_hdvs)} careful HDV(s) + all CAVs\")\n"
        "            world.tick()",
    ),
    # -----------------------------------------------------------------
    # E4. Fix the stale role-print (it claimed "avoidance OFF" for all HDVs).
    # -----------------------------------------------------------------
    (
        "E4 fix stale role-print",
        "avoidance per-profile",  # idempotency marker
        "                print(f\"   roles: {len(hdv_vehicles)} HDV (HOSTILE_MIX, avoidance OFF) + \"",
        "                print(f\"   roles: {len(hdv_vehicles)} HDV (HOSTILE_MIX, avoidance per-profile) + \"",
    ),
]


def apply(path: str) -> int:
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    changed = False
    missing = []
    for label, marker, old, new in PATCH_40_EDITS:
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
        print("usage: python fix_ablation_realism_and_determinism.py "
              "path/to/scripts/40_ablation_run.py", file=sys.stderr)
        sys.exit(1)
    sys.exit(apply(sys.argv[1]))
