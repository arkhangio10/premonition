"""Closed-loop image positioning: proposes capped single-joint steps. Never commands hardware."""
import math
from dataclasses import dataclass, field

import cv2
import numpy as np

# Measured 2026-11-02 near the post-fault pose, in tip image pixels per microsecond.
SENSITIVITY = {"base": (1.22, 0.48), "shoulder": (0.65, -2.0), "elbow": (-0.09, 0.59)}
# Pulses already traversed that day; the loop never explores beyond them.
TRAVERSED_US = {"base": (1499, 1802), "shoulder": (1367, 1450), "elbow": (1499, 1733)}
# Image pixel at the foot of the base axis in each fixed camera view.
BASE_PX = {"c922": (1200, 770), "usb": (1130, 880)}
# HSV range of the magenta tape on the outer jaw tip; None until it is tried on the hardware.
MARKER_HSV: tuple[tuple[int, int, int], tuple[int, int, int]] | None = None
# Half resolution. Blue parts up to BRIDGE_PX apart there (across the white housing or black servos) are joined
# at their closest points only, so the gap between forearm and gripper is never filled in.
TIP_SCALE, MIN_PART_PX, BRIDGE_PX, MAX_BASE_GAP_PX, TIP_BAND_PX = 2, 200, 75, 150, 40
TOLERANCE_PX, NOISE_PX = 15, 8
MARKER_MIN_PX = 120
MARKER_MARGIN = (8, 40, 40)
MARKER_MIN_SV = 60
MIN_STEP_US, MAX_STEP_US, BACKLASH_US = 20, 60, 20
MAX_RETRIES, MAX_MOVES = 2, 12
RETRY_GROWTH, LEARNING_RATE = 1.5, 0.5


@dataclass
class LoopState:
    target: tuple[float, float]
    sensitivity: dict = field(default_factory=lambda: dict(SENSITIVITY))
    direction: dict = field(default_factory=dict)
    retries: int = 0
    moves: int = 0
    pending: dict | None = None
    best_error: float = math.inf


@dataclass(frozen=True)
class Decision:
    kind: str
    joint: str | None = None
    delta: int | None = None
    reason: str | None = None


def locate_tip(image, base=BASE_PX["c922"]) -> tuple[float, float] | None:
    """End of the blue gripper: the blue point farthest from the base along the arm's body. None stops the loop."""
    small = cv2.resize(image, None, fx=1 / TIP_SCALE, fy=1 / TIP_SCALE, interpolation=cv2.INTER_AREA)
    blue = cv2.inRange(cv2.cvtColor(small, cv2.COLOR_BGR2HSV), (96, 91, 46), (127, 255, 255))
    blue = cv2.morphologyEx(blue, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(blue)
    parts = [k for k in range(1, count) if stats[k, cv2.CC_STAT_AREA] >= MIN_PART_PX]
    blue = np.isin(labels, parts).astype(np.uint8) * 255
    body = blue.copy()
    for i, a in enumerate(parts):
        distance = cv2.distanceTransform((labels != a).astype(np.uint8), cv2.DIST_L2, 5)
        a_points = np.argwhere(labels == a)
        for b in parts[i + 1:]:
            b_points = np.argwhere(labels == b)
            closest_b = b_points[np.argmin(distance[labels == b])]
            if distance[tuple(closest_b)] <= BRIDGE_PX:
                closest_a = a_points[np.argmin(((a_points - closest_b) ** 2).sum(axis=1))]
                cv2.line(body, (int(closest_a[1]), int(closest_a[0])), (int(closest_b[1]), int(closest_b[0])), 255, 3)
    ys, xs = np.nonzero(body)
    if not len(xs):
        return None
    gaps = np.hypot(xs * TIP_SCALE - base[0], ys * TIP_SCALE - base[1])
    if gaps.min() > MAX_BASE_GAP_PX:
        return None
    reached, steps = np.zeros_like(body), np.full(body.shape, -1, np.int32)
    reached[ys[np.argmin(gaps)], xs[np.argmin(gaps)]] = 255
    # Alternating square and cross steps approximate Euclidean distance along the body.
    kernels, step = (np.ones((3, 3), np.uint8), cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))), 0
    while True:
        grown = cv2.dilate(reached, kernels[step % 2]) & body
        if np.array_equal(grown, reached):
            break
        steps[(grown & ~reached & blue) > 0] = step
        reached, step = grown, step + 1
    if steps.max() < TIP_BAND_PX:
        return None
    # Both jaws end nearly as far along the body; averaging the whole end band keeps a tie from jumping between them.
    fy, fx = np.nonzero(steps >= steps.max() - TIP_BAND_PX)
    return float((fx.mean() + .5) * TIP_SCALE - .5), float((fy.mean() + .5) * TIP_SCALE - .5)


def locate_marker_tip(image) -> tuple[float, float] | None:
    """Centroid of the largest magenta blob, in the image's own pixels. None while MARKER_HSV is not configured."""
    if MARKER_HSV is None:
        return None
    mask = cv2.inRange(cv2.cvtColor(image, cv2.COLOR_BGR2HSV), MARKER_HSV[0], MARKER_HSV[1])
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
    big = [k for k in range(1, count) if stats[k, cv2.CC_STAT_AREA] >= MARKER_MIN_PX]
    if not big:
        return None
    k = max(big, key=lambda k: stats[k, cv2.CC_STAT_AREA])
    return float(centroids[k][0]), float(centroids[k][1])


def hsv_percentiles(image, box) -> dict | None:
    """5th, 50th and 95th percentile of H, S and V over the saturated, bright pixels in box = (x0, y0, x1, y1), clipped
    to the frame. None when no pixel qualifies."""
    x0, y0, x1, y1 = box
    crop = image[max(0, y0):max(0, y1), max(0, x0):max(0, x1)]
    if not crop.size:
        return None
    pixels = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    pixels = pixels[(pixels[:, 1] >= MARKER_MIN_SV) & (pixels[:, 2] >= MARKER_MIN_SV)]
    if not len(pixels):
        return None
    return {name: np.percentile(pixels[:, i], (5, 50, 95)).tolist() for i, name in enumerate("hsv")}


def propose_marker_hsv(stats: list[dict]) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """One MARKER_HSV range covering every box's 5th..95th percentiles plus MARKER_MARGIN."""
    low = [min(s[name][0] for s in stats) - m for name, m in zip("hsv", MARKER_MARGIN)]
    high = [max(s[name][2] for s in stats) + m for name, m in zip("hsv", MARKER_MARGIN)]
    return ((max(0, int(low[0])), max(0, int(low[1])), max(0, int(low[2]))),
            (min(179, math.ceil(high[0])), 255, 255))


def _room(joint: str, sign: int, pulses: dict) -> int:
    low, high = TRAVERSED_US[joint]
    return max(0, high - pulses[joint] if sign > 0 else pulses[joint] - low)


def _issue(state: LoopState, joint: str, delta: int, tip) -> Decision:
    sx, sy = state.sensitivity[joint]
    state.pending = {"joint": joint, "delta": delta, "tip": list(tip),
                     "predicted_px": math.hypot(sx * delta, sy * delta)}
    state.direction[joint] = 1 if delta > 0 else -1
    state.moves += 1
    return Decision("move", joint=joint, delta=delta)


def _review_pending(state: LoopState, tip, pulses: dict) -> Decision | None:
    """Learn from a visible step; a step that moved nothing retries wider, then stops."""
    step, state.pending = state.pending, None
    joint, delta = step["joint"], step["delta"]
    dx, dy = tip[0] - step["tip"][0], tip[1] - step["tip"][1]
    if math.hypot(dx, dy) >= max(NOISE_PX, 0.25 * step["predicted_px"]):
        state.retries = 0
        sx, sy = state.sensitivity[joint]
        state.sensitivity[joint] = (sx + LEARNING_RATE * (dx / delta - sx), sy + LEARNING_RATE * (dy / delta - sy))
        return None
    state.retries += 1
    sign = 1 if delta > 0 else -1
    wider = min(MAX_STEP_US, math.ceil(abs(delta) * RETRY_GROWTH), _room(joint, sign, pulses))
    if state.retries > MAX_RETRIES or not wider:
        return Decision("stop", reason=f"stalled:{joint}")
    return _issue(state, joint, sign * wider, tip)


def _best_step(state: LoopState, ex: float, ey: float, pulses: dict) -> tuple[str, int] | None:
    error = math.hypot(ex, ey)
    best, best_residual = None, error - max(NOISE_PX, 0.1 * error)
    for joint, (sx, sy) in state.sensitivity.items():
        wanted = (sx * ex + sy * ey) / (sx * sx + sy * sy)
        sign = 1 if wanted > 0 else -1
        room = _room(joint, sign, pulses)
        if room < MIN_STEP_US:
            continue
        delta = sign * min(MAX_STEP_US, max(MIN_STEP_US, round(abs(wanted))), room)
        residual = math.hypot(ex - sx * delta, ey - sy * delta)
        if residual <= best_residual:
            best, best_residual = (joint, delta), residual
    if best is None:
        return None
    joint, delta = best
    sign = 1 if delta > 0 else -1
    if state.direction.get(joint, sign) != sign:
        delta = sign * min(MAX_STEP_US, abs(delta) + BACKLASH_US, _room(joint, sign, pulses))
    return joint, delta


def decide(state: LoopState, tip, pulses: dict) -> Decision:
    if tip is None:
        return Decision("stop", reason="tip_not_visible")
    if state.pending:
        retry = _review_pending(state, tip, pulses)
        if retry:
            return retry
    ex, ey = state.target[0] - tip[0], state.target[1] - tip[1]
    error = math.hypot(ex, ey)
    if error <= TOLERANCE_PX:
        return Decision("done")
    if state.moves >= MAX_MOVES:
        return Decision("stop", reason="move_limit")
    if error > 1.5 * state.best_error:
        return Decision("stop", reason="diverging")
    state.best_error = min(state.best_error, error)
    step = _best_step(state, ex, ey, pulses)
    if step is None:
        return Decision("stop", reason="resolution_limit" if error <= 2 * TOLERANCE_PX else "out_of_reach")
    return _issue(state, *step, tip)
