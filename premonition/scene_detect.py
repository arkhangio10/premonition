"""Fast local detector for the orange sponge, in 1920x1080 pixels."""
import cv2
import numpy as np


def locate_object(image: np.ndarray) -> dict | None:
    # Brightness separates the sponge (V ~250, lit or washed out) from the reddish board and wood in shade (V <= 160).
    # At night the side USB sees the sponge's shaded face redder (H 2-11): hue starts at 5, and saturation >= 130 keeps
    # the brown table (S ~124) out.
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (5, 130, 160), (20, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if count < 2 or stats[1:, cv2.CC_STAT_AREA].max() < 3000:
        return None
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    ys, xs = np.nonzero(labels == k)
    x, _, w, _, area = (int(v) for v in stats[k])
    return {"cx": float(np.median(xs)), "cy": float(np.median(ys)),
            "top": float(np.percentile(ys, 1)), "bottom": float(np.percentile(ys, 99)),
            "x0": x, "x1": x + w, "area": area}
