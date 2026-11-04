"""Medidas deterministas sobre una imagen. No usa ningún modelo ni convierte píxeles en pulsos."""
import hashlib

import cv2
import numpy as np

from .models import CaptureRequest, Cell, Frame, Perception, PieceSpec, RegionMeasure


def decode_image(jpeg: bytes):
    if not jpeg:
        return None
    return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)


def check_frame(frame: Frame, request: CaptureRequest, seen: set[str]) -> list[str]:
    """Correlaciona por token e IDs. La frescura no depende de comparar relojes de PC y Jetson."""
    issues = []
    if not frame.jpeg:
        issues.append("empty_frame")
    if hashlib.sha256(frame.jpeg).hexdigest() != frame.sha256:
        issues.append("image_hash_mismatch")
    if frame.run_id != request.run_id:
        issues.append("wrong_run")
    if frame.step_id != request.step_id:
        issues.append("wrong_step")
    if frame.attempt != request.attempt:
        issues.append("wrong_attempt")
    if frame.phase != request.phase:
        issues.append("wrong_phase")
    if frame.command_id != request.command_id:
        issues.append("wrong_command")
    if frame.token != request.token:
        issues.append("stale_token")
    if frame.sha256 in seen:
        issues.append("repeated_image")
    return issues


def scene_issues(image, cell: Cell) -> list[str]:
    height, width = image.shape[:2]
    return [f"region_out_of_frame:{location.id}" for location in cell.locations
            if location.region is None or location.region.x < 0 or location.region.y < 0
            or location.region.w <= 0 or location.region.h <= 0
            or location.region.x + location.region.w > width
            or location.region.y + location.region.h > height]


def quality_metrics(image) -> dict[str, float]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return {"brightness": float(gray.mean()),
            "saturated": float((gray >= 250).mean()),
            "sharpness": float(cv2.Laplacian(gray, cv2.CV_64F).var())}


def frame_issues(jpeg: bytes, perception: Perception) -> list[str]:
    image = decode_image(jpeg)
    if image is None:
        return ["undecodable_image"]
    metrics = quality_metrics(image)
    issues = []
    if metrics["brightness"] < perception.brightness_min:
        issues.append("too_dark")
    if metrics["brightness"] > perception.brightness_max:
        issues.append("too_bright")
    if metrics["saturated"] > perception.saturated_max:
        issues.append("overexposed")
    if metrics["sharpness"] < perception.sharpness_min:
        issues.append("blurred")
    return issues


def foreground_mask(crop, perception: Perception):
    """Píxeles distintos del fondo calibrado, sin contar el oclusor oscuro."""
    delta = np.linalg.norm(crop.astype(np.float32) - np.array(perception.background_bgr, np.float32), axis=2)
    dark = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[..., 2] <= perception.occluder_val_max
    return (delta > perception.foreground_delta) & ~dark, dark


def _identity_scores(hsv, solid, pieces: list[PieceSpec]) -> dict[str, float]:
    total = int(solid.sum())
    scores = {}
    for piece in pieces:
        look = piece.appearance
        if look is None or total == 0:
            continue
        distance = np.abs(hsv[..., 0].astype(np.int16) - look.hue)
        distance = np.minimum(distance, 180 - distance)
        match = (distance <= look.hue_tol) & (hsv[..., 1] >= look.sat_min) & (hsv[..., 2] >= look.val_min)
        scores[piece.id] = float((match & solid).sum()) / total
    return scores


def measure_scene(image, cell: Cell) -> dict[str, RegionMeasure]:
    perception = cell.perception
    measures = {}
    for location in cell.locations:
        box = location.region
        crop = image[box.y:box.y + box.h, box.x:box.x + box.w]
        solid, dark = foreground_mask(crop, perception)
        scores = _identity_scores(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV), solid, cell.pieces)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best, score = ranked[0] if ranked else (None, 0.0)
        margin = score - (ranked[1][1] if len(ranked) > 1 else 0.0)
        offset = None
        if solid.any():
            rows, cols = np.nonzero(solid)
            offset = max(abs(float(cols.mean()) - box.w / 2) / (box.w / 2),
                         abs(float(rows.mean()) - box.h / 2) / (box.h / 2))
        measures[location.id] = RegionMeasure(
            region=location.id, occupancy=float(solid.mean()), occlusion=float(dark.mean()),
            best_piece=best, identity_score=score, identity_margin=margin, offset_norm=offset)
    return measures


def discrete_facts(measures: dict[str, RegionMeasure], perception: Perception) -> dict[str, str | None]:
    """Estado observado discreto: identifica las precondiciones de una referencia cacheada."""
    return {region: (m.best_piece if m.occupancy >= perception.occupied_min else None)
            for region, m in sorted(measures.items())}
