"""Verificadores A2 (medidas y predicados) y A3 (A2 más referencia generada congelada)."""
import hashlib
import json

import cv2
import numpy as np

from .models import Cell, Contract, Perception, Predicate, RegionMeasure, Verdict
from .perception import decode_image, foreground_mask

VERIFIER_VERSION = "a2a3-3"


def thresholds_sha256(cell: Cell) -> str:
    text = VERIFIER_VERSION + json.dumps(cell.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def _check(predicate: Predicate, m: RegionMeasure, p: Perception) -> tuple[str, str | None]:
    region = predicate.region
    if m.occlusion > p.occlusion_max:
        return "unknown", f"region_occluded:{region}"
    if predicate.kind == "region_empty":
        if m.occupancy <= p.empty_max:
            return "pass", None
        if m.occupancy < p.occupied_min:
            return "unknown", f"occupancy_ambiguous:{region}"
        return "fail", f"region_not_empty:{region}:{m.best_piece}"
    if m.occupancy <= p.empty_max:
        return "fail", f"piece_absent:{region}"
    if m.occupancy < p.occupied_min:
        return "unknown", f"occupancy_ambiguous:{region}"
    if m.identity_score < p.identity_min or m.identity_margin < p.identity_margin:
        return "unknown", f"identity_ambiguous:{region}"
    if m.best_piece != predicate.piece:
        return "fail", f"wrong_identity:{region}:{m.best_piece}"
    if m.offset_norm is None or m.offset_norm > p.position_tol_norm:
        return "fail", f"out_of_tolerance:{region}"
    return "pass", None


def _classify(contract: Contract, reason: str) -> str:
    code = reason.split(":")[0]
    if contract.role == "final":
        return "kit_incomplete"
    if contract.role in ("inspect", "pre"):
        return {"piece_absent": "missing_piece", "wrong_identity": "wrong_piece"}.get(code, "precondition_failed")
    if contract.action == "pick":
        same_piece = code == "region_not_empty" and reason.split(":")[2] == contract.piece_id
        return "grasp_failed" if same_piece else "ambiguous_state"
    return {"piece_absent": "piece_lost", "wrong_identity": "wrong_piece",
            "out_of_tolerance": "misplaced"}.get(code, "ambiguous_state")


def judge_a2(contract: Contract, measures: dict[str, RegionMeasure], perception: Perception) -> Verdict:
    results = [_check(p, measures[p.region], perception) for p in contract.predicates]
    failed = [reason for outcome, reason in results if outcome == "fail"]
    unknown = [reason for outcome, reason in results if outcome == "unknown"]
    if failed:
        return Verdict(outcome="fail", reasons=failed + unknown, failure_class=_classify(contract, failed[0]))
    if unknown:
        return Verdict(outcome="unknown", reasons=unknown)
    return Verdict(outcome="pass", reasons=[])


def _hue_histogram(image, mask):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0], mask.astype(np.uint8) * 255, [36], [0, 180]).ravel()
    return hist / hist.sum()


def region_similarity(observed, reference, cell: Cell, region_id: str) -> float:
    """Intersección de histogramas de tono del primer plano. Una apariencia, no una medida física."""
    box = cell.location(region_id).region
    crops = [image[box.y:box.y + box.h, box.x:box.x + box.w] for image in (observed, reference)]
    masks = [foreground_mask(crop, cell.perception)[0] for crop in crops]
    occupied = [bool(mask.mean() > cell.perception.empty_max) for mask in masks]
    if not all(occupied):
        return 1.0 if occupied[0] == occupied[1] else 0.0
    return float(np.minimum(_hue_histogram(crops[0], masks[0]), _hue_histogram(crops[1], masks[1])).sum())


def judge_a3(a2: Verdict, contract: Contract, post_jpeg: bytes, reference_jpeg: bytes | None,
             cell: Cell) -> tuple[Verdict, dict[str, float]]:
    """La referencia solo puede rebajar un pass de A2 a unknown; nunca aprueba ni redefine el contrato."""
    if reference_jpeg is None:
        return a2.model_copy(update={"reasons": a2.reasons + ["reference_missing"]}), {}
    observed = decode_image(post_jpeg)
    reference = decode_image(reference_jpeg)
    if reference is None:
        return a2.model_copy(update={"reasons": a2.reasons + ["reference_missing"]}), {}
    reference = cv2.resize(reference, (observed.shape[1], observed.shape[0]))
    similarity = {p.region: region_similarity(observed, reference, cell, p.region) for p in contract.predicates}
    low = [region for region, value in similarity.items() if value < cell.perception.reference_similarity_min]
    if a2.outcome != "pass" or not low:
        return a2, similarity
    return Verdict(outcome="unknown", reasons=[f"reference_mismatch:{r}" for r in low]), similarity
