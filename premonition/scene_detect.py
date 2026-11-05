"""Fast local detector for the orange sponge, in 1920x1080 pixels."""
import cv2
import numpy as np


def locate_object(image: np.ndarray) -> dict | None:
    # The front face in daylight shadow reaches V ~130; darker red board stays below that.
    # The USB sees the shaded face at H 1-3 in daylight and H 2-11 at night; saturation >= 130 keeps
    # the brown table (S ~124) out.
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    strong = cv2.inRange(hsv, (1, 130, 130), (20, 255, 255))
    # Recover the bright, pale face only when connected to a substantial saturated seed.
    pale = cv2.inRange(hsv, (0, 60, 200), (20, 255, 255))
    mask = strong | pale
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    seeds = np.bincount(labels[strong > 0], minlength=count)
    # Specks are rejected by area; a washed-out USB face keeps only a 1200-4700 px saturated core (4 Nov 16:05).
    candidates = [k for k in range(1, count) if stats[k, cv2.CC_STAT_AREA] >= 3000 and seeds[k] >= 1000]
    if not candidates:
        return None
    k = max(candidates, key=lambda k: stats[k, cv2.CC_STAT_AREA])
    ys, xs = np.nonzero(labels == k)
    x, _, w, _, area = (int(v) for v in stats[k])
    return {"cx": float(np.median(xs)), "cy": float(np.median(ys)),
            "top": float(np.percentile(ys, 1)), "bottom": float(np.percentile(ys, 99)),
            "x0": x, "x1": x + w, "area": area}
