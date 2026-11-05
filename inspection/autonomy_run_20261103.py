"""Autonomous pick-and-place from one instruction: optional self-scan, then Muse plan, grasp, place and judgement."""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from inspection import capability_scan_20261103 as capability_scan
from inspection.arm_checks_20261103 import STOP_MESSAGE, visit_poses
from premonition.arm_session import ArmSession
from premonition.atlas import configure_tip_detector
from premonition.autonomy import OBJECT_PHRASE, find_object, plan_task, run_task, safe_destination
from premonition.cli import PROJECT, load_env_file
from premonition.dual_camera import DualCamera
from premonition.grasp_policy import make_chooser
from premonition.jetson import read_commanded_pulses
from premonition.meta import client_from_env
from premonition.skills import grasp_target, load_memory, save_memory
from premonition.view_check import check_views, next_action, shift_atlas

HOST = "jetson-usb"
ROOT = Path("runs")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--scan", action="store_true", help="re-measure the atlas before the task")
    parser.add_argument("--dry-run", action="store_true", help="plan and print targets without starting the controller")
    learning = parser.add_mutually_exclusive_group()
    learning.add_argument("--no-learn", action="store_true", help="retry at fixed offsets instead of the grasp policy")
    learning.add_argument("--repeat-success", action="store_true", help="try a learned successful profile first, then resume the grasp policy")
    parser.add_argument("--record", action="store_true", help="keep five seconds of camera lead and tail for recording")
    args = parser.parse_args()
    load_env_file(PROJECT / ".env")
    client = client_from_env()
    if args.scan and not args.dry_run:
        capability_scan.main()
    capabilities = json.loads((ROOT / "real/calibration/capabilities.json").read_text(encoding="utf-8"))
    configure_tip_detector(capabilities)
    atlas = capabilities["atlas"]
    memory = load_memory(ROOT)
    if args.dry_run:
        cams = DualCamera(HOST)
        cams.start()
        try:
            frames = cams.snapshot()
            pulses = read_commanded_pulses(HOST)["commanded_us"]
            obj = find_object(client, frames, OBJECT_PHRASE)
            plan = plan_task(client, args.instruction, frames) if client else None
        finally:
            cams.close()
        print(json.dumps({"object": obj, "plan": plan,
                          "grasp_target": grasp_target(obj, memory) if obj.get("usb") else None,
                          "destination_from_current_pose": safe_destination(plan, pulses, obj, atlas),
                          "meta": client and {"calls": client.budget.calls, "usd": round(client.budget.usd, 4)}}, indent=1))
        return
    cams = DualCamera(HOST)
    cams.start()
    try:
        check = check_views(ROOT, cams.snapshot())
        action = next_action(check, args.scan)
        print(json.dumps(check, indent=1), flush=True)
        if args.scan and (check["action"] != "still" or "merged_from" not in capabilities):
            raise SystemExit("the scan did not finish or the views moved after it; rescan with "
                             "`python -m inspection.capability_scan_20261103` (sponge off the table)")
        trusted_views = (set(check["views"]) == {"c922", "usb"} and all(
            shift["method"] == "marker" and (shift["decision"] == "still"
                or (shift["decision"] == "rebase" and shift["moved_px"] <= 10))
            for shift in check["views"].values()))
        if action == "stop" or not trusted_views:
            raise SystemExit(STOP_MESSAGE)
        print(f"live view: http://127.0.0.1:{cams.serve()}", flush=True)
        if args.record:
            time.sleep(5)
        for view, shift in check["views"].items():
            if action == "rebase" and shift["decision"] == "rebase":
                atlas = shift_atlas(atlas, view, shift["matrix"])
        with ArmSession(HOST, ROOT) as arm:
            try:
                choose = None if args.no_learn else make_chooser(memory, np.random.default_rng(), repeat_success=args.repeat_success)
                result = run_task(args.instruction, arm, cams, atlas, client, memory, ROOT / "real/autonomy", choose=choose)
            finally:
                save_memory(ROOT, memory)
    finally:
        if args.record:
            time.sleep(5)
        cams.close()
    print(json.dumps(result))


if __name__ == "__main__":
    main()
