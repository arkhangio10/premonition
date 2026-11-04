"""Multi-joint visual servo: bring the gripper tip to a target marked in both camera views."""
import math
import time

import numpy as np

from .arm_session import LIMITS_US
from .atlas import GRASP_WRIST, local_jacobian, look, nearest_sample, predict_tip, stalled, travel

WEIGHTS = {"c922": 0.6, "usb": 1.0}
C922_GATE_PX = 80


def next_step(J: np.ndarray, error: np.ndarray, weights: np.ndarray, pulses: dict,
              joints=("base", "shoulder", "elbow"), cap_us=150, min_us=15, damping=0.05,
              bounds=None) -> dict[str, int] | None:
    limits = bounds or LIMITS_US
    low = np.array([limits[j][0] + 1 - pulses[j] for j in joints], float)
    high = np.array([limits[j][1] - 1 - pulses[j] for j in joints], float)
    WJ, We = weights[:, None] * J, weights * error
    # Joints that would cross a bound are held there and the others are solved again.
    free, dq = np.ones(len(joints), bool), np.zeros(len(joints))
    for _ in joints:
        F = WJ[:, free]
        dq[free] = np.linalg.solve(F.T @ F + damping ** 2 * np.eye(free.sum()), F.T @ (We - WJ[:, ~free] @ dq[~free]))
        out = free & ((dq < low) | (dq > high))
        if not out.any():
            break
        dq[out] = np.clip(dq[out], low[out], high[out])
        free &= ~out
        if not free.any():
            break
    peak = np.abs(dq).max()
    if peak > cap_us:
        dq *= cap_us / peak
    elif 0 < peak < min_us:
        dq *= min_us / peak
    dq[np.abs(dq) < min_us - 1e-9] = 0
    step = {j: int(round(pulses[j] + min(h, max(l, d)))) for j, d, l, h in zip(joints, dq, low, high)}
    applied = np.array([step[j] - pulses[j] for j in joints], float)
    if not applied.any() or np.linalg.norm(We - WJ @ applied) > 0.9 * np.linalg.norm(We):
        return None
    return step


def broyden(J: np.ndarray, dq: np.ndarray, dtip: np.ndarray) -> np.ndarray:
    seen = ~np.isnan(dtip)
    updated = J.copy()
    updated[seen] += np.outer(dtip[seen] - J[seen] @ dq, dq) / (dq @ dq)
    return updated


def _error(target: dict, tip: dict) -> tuple[np.ndarray, np.ndarray, dict]:
    error, weights, px = np.zeros(4), np.zeros(4), {}
    for i, view in enumerate(("c922", "usb")):
        if target.get(view) is None or tip.get(view) is None:
            px[view] = None
            continue
        # A None coordinate in the target is left free.
        for k in (0, 1):
            if target[view][k] is not None:
                error[2 * i + k] = target[view][k] - tip[view][k]
                weights[2 * i + k] = WEIGHTS[view]
        px[view] = round(math.hypot(*error[2 * i:2 * i + 2]), 1)
    return error, weights, px


def reach(session, cams, atlas, target: dict, tolerance={"c922": 30, "usb": 15}, max_moves=12,
          joints=("base", "shoulder", "elbow")) -> dict:
    began = time.perf_counter()
    # Start above the target so the last approach never comes up from under the object.
    above = [s for s in atlas if s["tip"].get("usb") and s["tip"]["usb"][1] <= target["usb"][1]]
    start = nearest_sample(above or atlas, target)["pulses"]
    travel(session, dict({j: GRASP_WRIST[j] for j in ("wrist_pitch", "wrist_roll")}, **start))
    J = local_jacobian(atlas, session.positions, joints)
    # Steps stay inside the scanned box: outside it the tip detector is unproven.
    box = {j: (min(s["pulses"][j] for s in atlas) - 1, max(s["pulses"][j] for s in atlas) + 1) for j in joints}
    moves, best, previous, px, trace = 0, math.inf, None, {}, []

    def result(ok, reason):
        return {"ok": ok, "reason": reason, "moves": moves, "error_px": px, "trace": trace,
                "pulses": dict(session.positions), "seconds": round(time.perf_counter() - began, 2)}

    def sense():
        tip = look(cams)
        # The C922 detector can jump to the upper arm when the gripper points at that camera.
        expected = predict_tip(atlas, session.positions, joints)["c922"]
        if tip.get("c922") and expected and math.dist(tip["c922"], expected) > C922_GATE_PX:
            tip = dict(tip, c922=None)
        if tip.get("usb") is None:
            return tip, None, None, None, math.inf
        error, weights, px = _error(target, tip)
        return tip, error, weights, px, float(np.linalg.norm(weights * error))

    while True:
        tip, error, weights, px, size = sense()
        if size > 1.5 * best and tip.get("usb") is not None:  # one jumped frame gets a second look
            tip, error, weights, px, size = sense()
        if tip.get("usb") is None:
            return result(False, "usb_tip_lost")
        trace.append({"tip": tip, "error_px": px, "step": None})
        if all(px[v] is None or px[v] <= tolerance[v] for v in px) and px["usb"] is not None:
            return result(True, "reached")
        if size > 1.5 * best:
            return result(False, "diverging")
        best = min(best, size)
        if previous is not None:
            dq, old_tip = previous
            if stalled(old_tip, tip, int(np.abs(dq).max())):
                return result(False, "stalled")
            dtip = np.array([np.nan] * 4)
            for i, view in enumerate(("c922", "usb")):
                if tip.get(view) is not None and old_tip.get(view) is not None:
                    dtip[2 * i:2 * i + 2] = np.subtract(tip[view], old_tip[view])
            J = broyden(J, dq, dtip)
        if moves >= max_moves:
            return result(False, "move_limit")
        step = next_step(J, error, weights, session.positions, joints, bounds=box)
        if step is None:
            return result(False, "no_progress")
        trace[-1]["step"] = step
        before = dict(session.positions)
        session.settle_move(step)
        previous = (np.array([session.positions[j] - before[j] for j in joints], float), tip)
        moves += 1
