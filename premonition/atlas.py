"""Self-scan of the arm: an atlas from joint pulses to the gripper tip in both camera views."""
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .arm_session import LIMITS_US, MAX_DELTA_US, OVERSHOOT_US
from . import visual_servo
from .visual_servo import BASE_PX, locate_tip

GRASP_WRIST = {"wrist_pitch": 1182, "wrist_roll": 1567, "gripper": 1616}
SCAN_GRID = {"base": [1150, 1250, 1350, 1450, 1550], "shoulder": [1640, 1560, 1480, 1400], "elbow": [2050, 2170, 2290]}
VIEW_ROWS = {"c922": (0, 1), "usb": (2, 3)}
STALL_US, STALL_PX = 40, 5
SETTLE_S = 0.4


def configure_tip_detector(capabilities: dict):
    """Use the same point detector that produced the loaded atlas."""
    bounds = capabilities.get("marker_hsv")
    point = capabilities.get("marker_point", "centroid")
    if point not in ("centroid", "lower_edge"):
        raise ValueError("invalid atlas marker_point configuration")
    if bounds is None:
        visual_servo.MARKER_HSV = None
        visual_servo.MARKER_POINT = "centroid"
        visual_servo.MARKER_ROIS = {}
        visual_servo.MARKER_JAW_DELTA = {}
        visual_servo.MARKER_ATLAS_GRIPPER_US = 1940
        return
    valid = (isinstance(bounds, (list, tuple)) and len(bounds) == 2
             and all(isinstance(row, (list, tuple)) and len(row) == 3 for row in bounds))
    if valid:
        valid = all(type(lo) is int and type(hi) is int and 0 <= lo <= hi <= cap
                    for lo, hi, cap in zip(*bounds, (179, 255, 255)))
    if not valid:
        raise ValueError("invalid atlas marker_hsv configuration")
    rois = capabilities.get("marker_rois", {})
    valid = isinstance(rois, dict) and (not rois or set(rois) == {"c922", "usb"})
    if valid:
        valid = all(isinstance(box, (list, tuple)) and len(box) == 4
                    and all(type(v) is int for v in box)
                    and 0 <= box[0] < box[2] <= 1920 and 0 <= box[1] < box[3] <= 1080
                    for box in rois.values())
    if not valid:
        raise ValueError("invalid atlas marker_rois configuration")
    delta = capabilities.get("jaw_open_minus_closed_px", {})
    valid = isinstance(delta, dict) and (not delta or set(delta) == {"c922", "usb"})
    if valid:
        valid = all(isinstance(row, (list, tuple)) and len(row) == 2
                    and all(type(v) in (int, float) and math.isfinite(v) and abs(v) <= 200 for v in row)
                    for row in delta.values())
    if not valid:
        raise ValueError("invalid atlas jaw_open_minus_closed_px configuration")
    opening = capabilities.get("gripper_us", 1940)
    if delta and (type(opening) is not int or not 1382 <= opening <= 1940):
        raise ValueError("invalid atlas jaw reference gripper_us")
    visual_servo.MARKER_HSV = tuple(tuple(row) for row in bounds)
    visual_servo.MARKER_POINT = point
    visual_servo.MARKER_ROIS = {view: list(box) for view, box in rois.items()}
    visual_servo.MARKER_JAW_DELTA = {view: list(row) for view, row in delta.items()}
    visual_servo.MARKER_ATLAS_GRIPPER_US = opening if delta else 1940


def gripper_projection_shift(view: str, opening: int, reference: int = 1940) -> np.ndarray:
    if visual_servo.MARKER_HSV is None or not visual_servo.MARKER_JAW_DELTA:
        return np.zeros(2)
    return np.asarray(visual_servo.MARKER_JAW_DELTA[view]) * ((opening - reference) / (1940 - 1382))


def at_gripper(samples: list, opening: int) -> list:
    """Reference the measured tip positions to the current opening before choosing a reach seed."""
    if visual_servo.MARKER_HSV is None or not visual_servo.MARKER_JAW_DELTA:
        return samples
    return [dict(s, pulses=dict(s["pulses"], gripper=opening), tip={view: None if point is None else
                 (np.asarray(point) + gripper_projection_shift(view, opening,
                     s["pulses"].get("gripper", visual_servo.MARKER_ATLAS_GRIPPER_US))).tolist()
                 for view, point in s["tip"].items()}) for s in samples]


def serpentine(grid) -> list[dict[str, int]]:
    # A closed tour of the shoulder x elbow cells; every base change happens with the shoulder at its highest value.
    shoulders, elbows = grid["shoulder"], grid["elbow"]
    cycle = [(s, elbows[0]) for s in shoulders]
    for i, s in enumerate(reversed(shoulders)):
        cycle += [(s, e) for e in (elbows[1:] if i % 2 == 0 else elbows[:0:-1])]
    poses, at = [], cycle[0]
    for base in grid["base"]:
        k = cycle.index(at)
        forward = cycle[k:] + cycle[:k]
        path = forward if forward[-1][0] == shoulders[0] else [forward[0]] + forward[:0:-1]
        poses += [{"base": base, "shoulder": s, "elbow": e} for s, e in path]
        at = path[-1]
    return poses


def stalled(before: dict, after: dict, delta_us: int) -> bool:
    if abs(delta_us) < STALL_US:
        return False
    moved = [math.dist(before[v], after[v]) for v in before if before.get(v) and after.get(v)]
    return bool(moved) and max(moved) < STALL_PX


def _scaled(pulses: dict, joints) -> np.ndarray:
    return np.array([pulses[j] / (LIMITS_US[j][1] - LIMITS_US[j][0]) for j in joints])


def local_jacobian(samples: list, pose: dict[str, int], joints=("base", "shoulder", "elbow")) -> np.ndarray:
    J = np.zeros((4, len(joints)))
    here = _scaled(pose, joints)
    for view, rows in VIEW_ROWS.items():
        seen = [s for s in samples if s["tip"].get(view) is not None]
        seen.sort(key=lambda s: float(np.linalg.norm(_scaled(s["pulses"], joints) - here)))
        near = seen[:6]
        if len(near) <= len(joints):
            continue
        X = np.array([[s["pulses"][j] for j in joints] + [1.0] for s in near], float)
        Y = np.array([s["tip"][view] for s in near], float)
        J[list(rows)] = np.linalg.lstsq(X, Y, rcond=None)[0][:-1].T
    return J


def nearest_sample(atlas: list, target: dict, weights=(0.6, 1.0)) -> dict:
    def cost(sample):
        total = weight_sum = 0.0
        for view, weight in zip(("c922", "usb"), weights):
            if target.get(view) is not None and sample["tip"].get(view) is not None:
                total += weight * math.hypot(*(t - s for t, s in zip(target[view], sample["tip"][view]) if t is not None))
                weight_sum += weight
        return total / weight_sum
    return min((s for s in atlas if s["tip"].get("usb") is not None), key=cost)


def predict_tip(atlas: list, pose: dict[str, int], joints=("base", "shoulder", "elbow")) -> dict:
    here, predicted = _scaled(pose, joints), {}
    for view, rows in VIEW_ROWS.items():
        seen = [s for s in atlas if s["tip"].get(view) is not None]
        if not seen:
            predicted[view] = None
            continue
        sample = min(seen, key=lambda s: float(np.linalg.norm(_scaled(s["pulses"], joints) - here)))
        dq = np.array([pose[j] - sample["pulses"][j] for j in joints], float)
        J = local_jacobian(atlas, sample["pulses"], joints)
        grip_shift = gripper_projection_shift(view, pose.get("gripper", visual_servo.MARKER_ATLAS_GRIPPER_US),
                                             sample["pulses"].get("gripper", visual_servo.MARKER_ATLAS_GRIPPER_US))
        predicted[view] = (np.asarray(sample["tip"][view]) + J[list(rows)] @ dq + grip_shift).tolist()
    return predicted


def merge_scans(first: list, second: list, agree_px: float = 15) -> list:
    # Two passes over the same poses: a view both passes agree on is averaged, a disagreement is dropped.
    merged = []
    for a, b in zip(first, second):
        tip = {}
        for view in ("c922", "usb"):
            p, q = a["tip"].get(view), b["tip"].get(view)
            if p and q:
                tip[view] = [round((p[0] + q[0]) / 2, 1), round((p[1] + q[1]) / 2, 1)] if math.dist(p, q) <= agree_px else None
            else:
                tip[view] = p or q
        merged.append({"pulses": b["pulses"], "tip": tip, "t": b["t"], "tip_blue": b.get("tip_blue")})
    return merged


def detector_report(first: list, second: list, agree_px: float = 15) -> dict:
    report = {}
    for view in ("c922", "usb"):
        tips = [s["tip"].get(view) for s in first + second]
        jumps = {key: sum(bool(a[key].get(view) and b[key].get(view) and math.dist(a[key][view], b[key][view]) > agree_px)
                          for a, b in zip(first, second)) for key in ("tip", "tip_blue")}
        gaps = [math.dist(s["tip"][view], s["tip_blue"][view]) for s in first + second if s["tip"].get(view) and s["tip_blue"].get(view)]
        report[view] = {"visible": sum(t is not None for t in tips) / len(tips) if tips else None,
                        "jumps_tip": jumps["tip"], "jumps_blue": jumps["tip_blue"],
                        "median_tip_vs_blue_px": round(float(np.median(gaps)), 2) if gaps else None}
    return report


def backlash_us(gap_px: float, column_usb: np.ndarray) -> float:
    return gap_px / float(np.linalg.norm(column_usb))


def travel(session, pose: dict[str, int], overshoot_us: int | None = None):
    # Shoulder up first and down last, so long moves pass above the table; each order stays within MAX_DELTA_US.
    legs = []
    if pose.get("shoulder", 0) > session.positions["shoulder"]:
        legs.append({"shoulder": pose["shoulder"]})
    legs.append({j: v for j, v in pose.items() if j != "shoulder"})
    if "shoulder" in pose:
        legs.append({"shoulder": pose["shoulder"]})
    for leg in legs:
        cap = MAX_DELTA_US - (max((OVERSHOOT_US[j] for j in leg), default=0) if overshoot_us is None else overshoot_us)
        while True:
            step = {j: session.positions[j] + max(-cap, min(cap, v - session.positions[j])) for j, v in leg.items()}
            if step == leg:
                if any(session.positions[j] != v for j, v in leg.items()):
                    session.settle_move(leg, overshoot_us)
                break
            session.move(step)


def _rounded(tips: dict) -> dict:
    return {view: None if tip is None else [round(tip[0], 1), round(tip[1], 1)] for view, tip in tips.items()}


def locate_tips(frames) -> dict:
    if visual_servo.MARKER_HSV is not None:
        return _rounded({view: visual_servo.locate_marker_tip(frame.image, visual_servo.MARKER_ROIS.get(view))
                         for view, frame in frames.items()})
    return locate_tips_blue(frames)


def locate_tips_blue(frames) -> dict:
    return _rounded({view: locate_tip(frame.image, BASE_PX[view]) for view, frame in frames.items()})


def _snap(cams, tries: int = 3) -> tuple[dict, dict]:
    for _ in range(tries):
        frames = cams.snapshot(after=time.perf_counter() + SETTLE_S)
        tips = locate_tips(frames)
        if tips["usb"] is not None:
            break
    return tips, frames


def look(cams, tries: int = 3) -> dict:
    return _snap(cams, tries)[0]


def scan(session, cams, grid, out: Path, frames_dir: Path | None = None) -> dict:
    poses = serpentine(grid)
    atlas, stalls, move_s, stop = [], [], [], None
    skip_base = None
    for i, pose in enumerate(poses):
        if pose["base"] == skip_base:
            continue
        before = dict(session.positions)
        began = time.perf_counter()
        travel(session, pose)
        move_s.append(time.perf_counter() - began)
        tip, frames = _snap(cams)
        if frames_dir is not None:
            Path(frames_dir).mkdir(parents=True, exist_ok=True)
            for view, frame in frames.items():
                (Path(frames_dir) / f"{i:03d}_{view}.jpg").write_bytes(frame.jpeg)
        if tip["usb"] is None:
            stop = {"reason": "usb_tip_lost", "pulses": dict(session.positions)}
            break
        delta = max(abs(session.positions[j] - before[j]) for j in pose)
        if atlas and stalled(atlas[-1]["tip"], tip, delta):
            stalls.append({"pulses": dict(session.positions), "from": before, "tip": tip})
            skip_base = pose["base"]
            continue
        atlas.append({"pulses": {j: session.positions[j] for j in ("base", "shoulder", "elbow")}, "tip": tip,
                      "tip_blue": dict(tip) if visual_servo.MARKER_HSV is None else locate_tips_blue(frames), "t": time.time()})
    center = {j: grid[j][len(grid[j]) // 2] for j in ("base", "shoulder", "elbow")}
    away = dict(center, base=grid["base"][0], shoulder=grid["shoulder"][0])
    visits = []
    if stop is None:
        for _ in range(3):
            travel(session, away)
            travel(session, center)
            visits.append(look(cams))
    repeatability = {}
    for view in ("c922", "usb"):
        points = [v[view] for v in visits if v[view] is not None]
        repeatability[view] = (round(float(np.sqrt(np.var(points, axis=0).sum())), 2) if len(points) == 3 else None)
    report = {"atlas": atlas, "stalls": stalls, "repeatability_px": repeatability, "repeat_visits": visits,
              "move_s_mean": round(float(np.mean(move_s)), 3) if move_s else None, "stop": stop,
              "grid": grid, "created_at": datetime.now(timezone.utc).isoformat(),
              "marker_hsv": visual_servo.MARKER_HSV, "marker_point": visual_servo.MARKER_POINT,
              "marker_rois": visual_servo.MARKER_ROIS, "jaw_open_minus_closed_px": visual_servo.MARKER_JAW_DELTA,
              "gripper_us": session.positions.get("gripper", 1940), "overshoot_us": dict(OVERSHOOT_US)}
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    return report
