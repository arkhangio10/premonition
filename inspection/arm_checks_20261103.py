"""Checks around the arm and its cameras: `views` (cameras only), `hsv` (magenta tape range from a live frame, cameras only),
`agree` (atlas against three live poses), `backlash` (per-joint overshoot gap at one pose), `fit` (camera and kinematic model from the saved atlases, no hardware),
`scale` (mm per model unit and table plane from the table ArUco, cameras only) and `holdout` (model and atlas error at random poses)."""
import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np

from premonition import arm_model, visual_servo
from premonition.arm_session import LIMITS_US, ArmSession
from premonition.atlas import GRASP_WRIST, SCAN_GRID, VIEW_ROWS, backlash_us, local_jacobian, look, predict_tip, travel
from premonition.dual_camera import DualCamera
from premonition.view_check import agreement, check_views, save_reference, shift_atlas, table_marker

HOST = "jetson-usb"
ROOT = Path("runs")
STOP_MESSAGE = "camera moved: run python -m inspection.capability_scan_20261103 with the sponge off the table"
NOT_SAVED = f"reference not saved because the views moved; {STOP_MESSAGE} to make the shift permanent"
SAVE_ACTIONS = ("still", "no_reference")
EXTRA_POSES = ({"base": 1150, "shoulder": 1640, "elbow": 2050}, {"base": 1550, "shoulder": 1640, "elbow": 2290})
ATLASES = {"current": "capabilities.json", "oldcams": "capabilities_oldcams_20261103.json",
           "gooseneck": "capabilities_gooseneck_20261103.json"}
G_BASE_DEG_PER_US = 0.084
BACKLASH_POSE = dict(GRASP_WRIST, base=1550, shoulder=1480, elbow=2170)
BACKLASH_STEP_US = 60
BACKLASH_REPS = 3
HSV_DIR = Path("inspection")
MODEL_FILE = "real/calibration/arm_model.json"


def visit_poses(arm, cams, atlas) -> dict:
    center = {j: SCAN_GRID[j][len(SCAN_GRID[j]) // 2] for j in ("base", "shoulder", "elbow")}
    travel(arm, dict(GRASP_WRIST, shoulder=SCAN_GRID["shoulder"][0]))
    seen = []
    for pose in (center, *EXTRA_POSES):
        pose = dict(GRASP_WRIST, **pose)
        travel(arm, pose)
        seen.append((pose, look(cams)))
    return agreement(atlas, seen)


def views(args):
    cams = DualCamera(HOST)
    cams.start()
    try:
        frames = cams.snapshot()
    finally:
        cams.close()
    check = check_views(ROOT, frames)
    print(json.dumps({"check": check,
                      "marker_seen": {view: table_marker(frame.image) is not None for view, frame in frames.items()}}, indent=1))
    if args.save and check["action"] not in SAVE_ACTIONS:
        print(NOT_SAVED)
    elif args.save:
        save_reference(ROOT, frames)


def hsv(args):
    cams = DualCamera(HOST)
    cams.start()
    try:
        frames = cams.snapshot()
    finally:
        cams.close()
    for view, frame in frames.items():
        cv2.imwrite(str(HSV_DIR / f"marker_hsv_{view}.jpg"), frame.image)
    boxes = [(view, tuple(int(v) for v in corners)) for view, *corners in args.box or []]
    proposed = None
    if boxes:
        stats = [visual_servo.hsv_percentiles(frames[view].image, box) for view, box in boxes]
        for (view, box), stat in zip(boxes, stats):
            print(json.dumps({"view": view, "box": box, **stat}) if stat else f"{view} {box}: no saturated bright pixel in the box")
        stats = [stat for stat in stats if stat]
        if stats:
            proposed = visual_servo.propose_marker_hsv(stats)
            print(f"MARKER_HSV = {proposed}")
    configured = visual_servo.MARKER_HSV
    visual_servo.MARKER_HSV = proposed or configured
    try:
        for view, frame in frames.items():
            found = visual_servo.locate_marker_tip(frame.image)
            inside = [x0 <= found[0] <= x1 and y0 <= found[1] <= y1
                      for v, (x0, y0, x1, y1) in boxes if v == view] if found else []
            active = visual_servo.MARKER_HSV
            accepts = None if active is None else round(
                float(cv2.inRange(cv2.cvtColor(frame.image, cv2.COLOR_BGR2HSV), *active).mean()) / 255, 4)
            print(json.dumps({"view": view, "marker": found, "inside_box": any(inside) if any(v == view for v, _ in boxes) else None,
                              "accepts": accepts}))
    finally:
        visual_servo.MARKER_HSV = configured


def agree(args):
    atlas = json.loads((ROOT / "real/calibration/capabilities.json").read_text(encoding="utf-8"))["atlas"]
    cams = DualCamera(HOST)
    cams.start()
    try:
        print(f"live view: http://127.0.0.1:{cams.serve()}", flush=True)
        check = check_views(ROOT, cams.snapshot())
        print(json.dumps(check, indent=1))
        if check["action"] == "rescan":
            raise SystemExit(STOP_MESSAGE)
        for view, shift in check["views"].items():
            if shift["decision"] == "rebase":
                atlas = shift_atlas(atlas, view, shift["matrix"])
        with ArmSession(HOST, ROOT) as arm:
            result = visit_poses(arm, cams, atlas)
        print(json.dumps(result, indent=1))
        if args.save and check["action"] not in SAVE_ACTIONS:
            print(NOT_SAVED)
        elif args.save and result["ok"]:
            save_reference(ROOT, cams.snapshot())
    finally:
        cams.close()


def backlash_runs(arm, cams, joint: str) -> tuple[dict, dict]:
    target = BACKLASH_POSE[joint]
    approach = {"B": (-BACKLASH_STEP_US, arm.move), "A": (BACKLASH_STEP_US, arm.settle_move), "C": (BACKLASH_STEP_US, arm.move)}
    tips = {name: [] for name in approach}
    for name, (offset, arrive) in approach.items():
        for _ in range(BACKLASH_REPS):
            arm.move({joint: target + offset})
            arrive({joint: target})
            tips[name].append(look(cams))
    mean = {name: {view: np.mean([t[view] for t in seen if t[view] is not None], axis=0) if any(t[view] is not None for t in seen) else None
                   for view in VIEW_ROWS} for name, seen in tips.items()}
    gaps = {name: {view: None if mean[name][view] is None or mean["B"][view] is None
                   else round(float(np.linalg.norm(mean[name][view] - mean["B"][view])), 1) for view in VIEW_ROWS} for name in ("A", "C")}
    return gaps, tips


def backlash(args):
    atlas = json.loads((ROOT / "real/calibration/capabilities.json").read_text(encoding="utf-8"))["atlas"]
    jacobian = local_jacobian(atlas, BACKLASH_POSE)
    cams = DualCamera(HOST)
    cams.start()
    try:
        print(f"live view: http://127.0.0.1:{cams.serve()}", flush=True)
        report = {}
        with ArmSession(HOST, ROOT) as arm:
            travel(arm, BACKLASH_POSE)
            for column, joint in enumerate(("base", "shoulder", "elbow")):
                gaps, tips = backlash_runs(arm, cams, joint)
                sensitivity = jacobian[list(VIEW_ROWS["usb"]), column]
                report[joint] = {"gap_px": gaps, "tips": tips,
                                 "gap_us": {name: None if gap["usb"] is None else round(backlash_us(gap["usb"], sensitivity), 1)
                                            for name, gap in gaps.items()}}
                print(json.dumps({joint: report[joint]}), flush=True)
        (ROOT / "real/calibration/backlash_20261103.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=1))
    finally:
        cams.close()


def acceptance(fitted, hold) -> dict:
    # Task 1.2's criteria on `current`: holdout medians against the atlas, edge bases where the atlas extrapolates.
    rms, folds = fitted["rms_px"]["current"], hold["per_fold"]
    verdicts = {f"rms_le_6px/{v}": rms[v] <= 6.0 for v in rms}
    verdicts |= {f"holdout_median_le_1.5x_atlas/{v}": hold["model_px"][v]["median"] <= 1.5 * hold["atlas_px"][v]["median"]
                 for v in hold["model_px"]}
    verdicts |= {f"holdout_below_atlas/{b}/{v}": folds[b]["model_px"][v]["median"] < folds[b]["atlas_px"][v]["median"]
                 for b in (1150, 1650) if b in folds for v in folds[b]["model_px"]}
    verdicts |= {f"holdout_below_atlas/{b}": None for b in (1150, 1650) if b not in folds}
    g_base = math.degrees(abs(fitted["kin"]["g_base"]))
    verdicts["g_base_within_15pct_of_0.084"] = abs(g_base / G_BASE_DEG_PER_US - 1) <= 0.15
    return verdicts


def fit(args):
    calibration = ROOT / "real/calibration"
    atlases = {name: json.loads((calibration / file).read_text(encoding="utf-8"))["atlas"] for name, file in ATLASES.items()}
    fitted = arm_model.fit(atlases)
    if not fitted["ok"]:
        raise SystemExit(f"fit not ok, nothing written: {json.dumps(fitted)}")
    holdouts = {name: arm_model.holdout(atlas) for name, atlas in atlases.items()}
    verdicts = acceptance(fitted, holdouts["current"])
    summary = {"ok": fitted["ok"], "approximate": not all(verdicts.values()), "rms_px": fitted["rms_px"]["current"],
               "rms_px_all": fitted["rms_px_all"]["current"], "inlier_px": arm_model.INLIER_PX,
               "holdout": {"model_px": holdouts["current"]["model_px"], "atlas_px": holdouts["current"]["atlas_px"]},
               "acceptance": verdicts}
    report = {"summary": summary, "fit": fitted, "holdout": holdouts,
              "epipolar_report": {name: arm_model.epipolar_report(atlas) for name, atlas in atlases.items()}}
    (calibration / "arm_model.json").write_text(
        json.dumps(arm_model.to_json(arm_model.model_for(fitted, "current")), indent=1) + "\n", encoding="utf-8")
    (calibration / "arm_model_fit_report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"kin": fitted["kin"], "summary": summary, "epipolar_report": report["epipolar_report"]}, indent=1))


def scale(args):
    cams = DualCamera(HOST)
    cams.start()
    try:
        frames = cams.snapshot()
    finally:
        cams.close()
    corners = {view: table_marker(frame.image) for view, frame in frames.items()}
    if any(c is None for c in corners.values()):
        print(f"table marker not seen in {[view for view, c in corners.items() if c is None]}, nothing written")
        return
    model = arm_model.from_json(json.loads((ROOT / MODEL_FILE).read_text(encoding="utf-8")))
    result = arm_model.scale_from_marker(model, corners)
    model.mm_per_unit, model.table = result["mm_per_unit"], result["table"]
    (ROOT / MODEL_FILE).write_text(json.dumps(arm_model.to_json(model), indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))


def holdout_errors(model, atlas, samples) -> dict:
    model_px, atlas_px = {}, {}
    for s in samples:
        point, predicted = arm_model.fk(model, s["pulses"])[2], predict_tip(atlas, s["pulses"])
        for view, tip in s["tip"].items():
            if tip is not None and view in model.cams:
                model_px.setdefault(view, []).append(float(np.linalg.norm(arm_model.project(model, view, [point])[0] - tip)))
                atlas_px.setdefault(view, []).append(float(np.linalg.norm(np.subtract(predicted[view], tip))))
    return {"model_px": arm_model._stats(model_px), "atlas_px": arm_model._stats(atlas_px),
            "mm": None if model.mm_per_unit is None else arm_model.tip_error_mm(model, samples)}


def holdout(args):
    model = arm_model.from_json(json.loads((ROOT / MODEL_FILE).read_text(encoding="utf-8")))
    atlas = json.loads((ROOT / "real/calibration/capabilities.json").read_text(encoding="utf-8"))["atlas"]
    box = {j: (max(min(s["pulses"][j] for s in atlas), LIMITS_US[j][0] + 1), min(max(s["pulses"][j] for s in atlas), LIMITS_US[j][1] - 1))
           for j in ("base", "shoulder", "elbow")}
    rng = np.random.default_rng()
    poses = [{j: int(rng.integers(lo, hi + 1)) for j, (lo, hi) in box.items()} for _ in range(args.poses)]
    cams = DualCamera(HOST)
    cams.start()
    try:
        print(f"live view: http://127.0.0.1:{cams.serve()}", flush=True)
        samples = []
        with ArmSession(HOST, ROOT) as arm:
            for pose in poses:
                travel(arm, dict(GRASP_WRIST, **pose))
                samples.append({"pulses": pose, "tip": look(cams)})
    finally:
        cams.close()
    print(json.dumps({"samples": samples}))
    print(json.dumps(holdout_errors(model, atlas, samples), indent=1))


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for name, run, text in (("views", views, "print the view check and whether the table ArUco is seen"),
                            ("agree", agree, "visit three poses and compare the atlas with what is seen")):
        command = commands.add_parser(name, help=text)
        command.add_argument("--save", action="store_true", help="save the view reference if no view moved" + (" and the atlas agrees" if name == "agree" else ""))
        command.set_defaults(run=run)
    command = commands.add_parser("hsv", help="save one frame per view; propose MARKER_HSV from --box boxes, or check the configured one")
    command.add_argument("--box", nargs=5, action="append", metavar=("VIEW", "X0", "Y0", "X1", "Y1"),
                         help="a box inside the tape: no table, jaw or edge pixels")
    command.set_defaults(run=hsv)
    commands.add_parser("backlash", help="measure the overshoot gap of base, shoulder and elbow at one pose, with the sponge off the table"
                        ).set_defaults(run=backlash)
    commands.add_parser("fit", help="fit cameras and kinematics to the saved atlases; write arm_model.json and the fit report"
                        ).set_defaults(run=fit)
    commands.add_parser("scale", help="write mm_per_unit and the table plane into arm_model.json from the table ArUco"
                        ).set_defaults(run=scale)
    command = commands.add_parser("holdout", help="visit random poses inside the scanned box, with the sponge off the table; print model, atlas and mm tip error")
    command.add_argument("--poses", type=int, default=10)
    command.set_defaults(run=holdout)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
