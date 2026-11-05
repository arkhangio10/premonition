"""Did a fixed camera move? Each view against a saved reference: still, rebase BASE_PX and the atlas, or rescan."""
import copy
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from . import visual_servo
from .atlas import predict_tip
from .visual_servo import BASE_PX

TABLE_MARKER_ID, TABLE_MARKER_MM = 0, 50.0
STILL_PX, REBASE_PX = 3.0, 60.0
TEST_POINTS = ((960, 540), (480, 270), (1440, 270), (480, 810), (1440, 810))
# locate_tip's blue and locate_object's orange: the arm and the sponge move on their own.
MOVING_HSV = (((96, 91, 46), (127, 255, 255)), ((10, 110, 170), (20, 255, 255)))
MASK_GROW_PX = 25
ECC_CRITERIA = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-6)
REFERENCE = "real/calibration/view_reference.json"
SEVERITY = ("still", "rebase", "rescan")


def table_marker(image) -> np.ndarray | None:
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    # The USB view sees the 50 mm tag at ~100 px and slightly blurred: the default 3-23 px window missed it in 2 of 3 frames.
    params.adaptiveThreshWinSizeMin, params.adaptiveThreshWinSizeMax, params.adaptiveThreshWinSizeStep = 3, 53, 4
    # Sample inside each bit, away from the blurred cell borders; this dictionary corrects one bit.
    params.perspectiveRemovePixelPerCell = 12
    params.perspectiveRemoveIgnoredMarginPerCell = 0.35
    params.errorCorrectionRate = 1.0
    marker = _detect_table_marker(image, params)
    if marker is not None:
        return marker
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sharp = cv2.addWeighted(gray, 2, cv2.GaussianBlur(gray, (0, 0), 1.0), -1, 0)
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_APRILTAG
    params.perspectiveRemovePixelPerCell = 4
    params.perspectiveRemoveIgnoredMarginPerCell = 0.13
    params.errorCorrectionRate = 0.6
    return _detect_table_marker(sharp, params)


def _detect_table_marker(image, params) -> np.ndarray | None:
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), params)
    corners, ids, _ = detector.detectMarkers(image)
    for found, marker_id in zip(corners, [] if ids is None else ids.ravel()):
        if marker_id == TABLE_MARKER_ID:
            return found.reshape(4, 2).astype(np.float32)
    return None


def background_mask(image) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    ranges = MOVING_HSV if visual_servo.MARKER_HSV is None else MOVING_HSV + (visual_servo.MARKER_HSV,)
    moving = np.zeros(image.shape[:2], np.uint8)
    for low, high in ranges:
        moving |= cv2.inRange(hsv, low, high)
    grow = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * MASK_GROW_PX + 1,) * 2)
    return cv2.bitwise_not(cv2.dilate(moving, grow))


def apply(matrix, point) -> tuple[float, float]:
    (a, b, c), (d, e, f) = np.asarray(matrix, float)
    return float(a * point[0] + b * point[1] + c), float(d * point[0] + e * point[1] + f)


def view_shift(reference, current, reference_marker=None) -> dict:
    """The 2x3 matrix that carries reference pixels to current pixels."""
    # Use raw-frame corners saved at calibration: a JPEG can lose a slanted tag.
    try:
        before = np.asarray(reference_marker, dtype=np.float32)
    except (TypeError, ValueError):
        before = None
    if before is None or before.shape != (4, 2) or not np.isfinite(before).all():
        before = table_marker(reference)
    after = table_marker(current)
    if before is not None and after is not None:
        # On real frames the tag spans ~100 px and its corners jitter 1-3 px: a fitted rotation/scale, extrapolated to
        # TEST_POINTS ~800 px away, read 5-107 px of motion from still cameras. Only the tag's shift is trusted.
        dx, dy = (after - before).mean(axis=0)
        ok, method, matrix = True, "marker", np.array([[1, 0, dx], [0, 1, dy]], np.float32)
    else:
        method = "ecc"
        gray = [cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) for image in (reference, current)]
        small = [cv2.resize(g, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA).astype(np.float32) for g in gray]
        (dx, dy), _ = cv2.phaseCorrelate(*small, cv2.createHanningWindow(small[0].shape[::-1], cv2.CV_32F))
        matrix = np.array([[1, 0, 4 * dx], [0, 1, 4 * dy]], np.float32)
        try:
            # Each mask stays in its own frame; ECC scores only pixels that are background in both.
            _, matrix = cv2.findTransformECCWithMask(*gray, background_mask(reference), background_mask(current),
                                                     matrix, cv2.MOTION_EUCLIDEAN, ECC_CRITERIA)
            ok = True
        except cv2.error:
            ok = False
    moved = max(math.dist(p, apply(matrix, p)) for p in TEST_POINTS)
    return {"ok": ok, "method": method, "matrix": matrix.tolist(), "moved_px": moved}


def decide(shift) -> str:
    # Written so that a NaN shift falls through to a rescan.
    if shift["ok"] and shift["moved_px"] <= STILL_PX:
        return "still"
    if shift["ok"] and shift["moved_px"] <= REBASE_PX:
        return "rebase"
    return "rescan"


def shift_atlas(atlas, view, matrix) -> list:
    moved = copy.deepcopy(atlas)
    for sample in moved:
        if sample["tip"].get(view) is not None:
            sample["tip"][view] = list(apply(matrix, sample["tip"][view]))
    return moved


def rebase(view, matrix):
    BASE_PX[view] = apply(matrix, BASE_PX[view])


def save_reference(root, frames) -> dict:
    path = Path(root) / REFERENCE
    path.parent.mkdir(parents=True, exist_ok=True)
    reference = {"base_px": {}, "marker": {}, "created_at": datetime.now(timezone.utc).isoformat()}
    for view, frame in frames.items():
        cv2.imwrite(str(path.parent / f"view_reference_{view}.jpg"), frame.image)
        corners = table_marker(frame.image)
        reference["base_px"][view] = list(BASE_PX[view])
        reference["marker"][view] = None if corners is None else corners.tolist()
    path.write_text(json.dumps(reference, indent=1) + "\n", encoding="utf-8")
    return reference


def check_views(root, frames) -> dict:
    """Restores BASE_PX to the reference's, then follows each view: always with the ArUco, by ECC only on a rebase."""
    path = Path(root) / REFERENCE
    if not path.exists():
        return {"action": "no_reference", "views": {}}
    reference = json.loads(path.read_text(encoding="utf-8"))
    views = {}
    for view, frame in frames.items():
        BASE_PX[view] = tuple(reference["base_px"][view])
        shift = view_shift(cv2.imread(str(path.parent / f"view_reference_{view}.jpg")), frame.image,
                           reference_marker=reference.get("marker", {}).get(view))
        decision = decide(shift)
        if shift["method"] == "marker" or decision == "rebase":
            rebase(view, shift["matrix"])
        views[view] = dict(shift, decision=decision)
    return {"action": max((v["decision"] for v in views.values()), key=SEVERITY.index), "views": views}


def agreement(atlas, seen: list[tuple[dict, dict]], limits={"usb": 10, "c922": 20}) -> dict:
    """Largest gap per view between the tips seen at some poses and the atlas's prediction for them.

    Without a single USB tip, the view reach relies on, there is no evidence and the check fails."""
    gaps = {view: [] for view in limits}
    for pose, tips in seen:
        predicted = predict_tip(atlas, pose)
        for view in limits:
            if tips.get(view) is not None and predicted[view] is not None:
                gaps[view].append(math.dist(tips[view], predicted[view]))
    error = {view: max(g) if g else None for view, g in gaps.items()}
    ok = error.get("usb") is not None and all(e is None or e <= limits[view] for view, e in error.items())
    return {"ok": ok, "error_px": error}


def next_action(check: dict, scan_requested: bool) -> str:
    return {"still": "continue", "no_reference": "continue", "rebase": "rebase",
            "rescan": "scan" if scan_requested else "stop"}[check["action"]]
