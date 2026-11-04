"""Muse plans the task and judges each phase; local checks decide, so Muse never blocks or overrides motion."""
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from .atlas import SETTLE_S, locate_tips, predict_tip
from .scene_detect import locate_object
from .skills import grasp, place

SIZE = (1920, 1080)
PLAN_TIMEOUT_S = 30
JUDGE_TIMEOUT_S = 20
OBJECT_PHRASE = "orange sponge"
DEFAULT_BASE_SHIFT_US = 117
BASE_RANGE_US = (1150, 1560)
NEXT_OFFSET = {"shift_outward": -15, "shift_inward": 15, "retry": 0, "lower_more": 0}
POOL = ThreadPoolExecutor(max_workers=3)

PIXEL = {"type": "array", "items": {"type": "integer"}}
PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["object", "destination", "destination_px", "obstacles", "feasible", "reason"],
    "properties": {
        "object": {"type": "string"}, "destination": {"type": "string"},
        "destination_px": {"type": "object", "additionalProperties": False, "required": ["c922", "usb"],
                           "properties": {"c922": PIXEL, "usb": PIXEL}},
        "obstacles": {"type": "array", "items": {"type": "string"}},
        "feasible": {"type": "boolean"}, "reason": {"type": "string"}}}
VERDICT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["success", "reason", "next"],
    "properties": {
        "success": {"type": "boolean"}, "reason": {"type": "string"},
        "next": {"type": "string", "enum": ["continue", "retry", "shift_outward", "shift_inward", "lower_more", "ask_human"]}}}

PLAN_SYSTEM = (
    "You plan one pick-and-place task for a small desk arm with a blue gripper, seen by two fixed cameras: "
    "'c922' (front, above the table) and 'usb' (a second view). Pixel coordinates are integers in the 1920x1080 image. "
    "Name the object to move, describe where it should go, and give destination_px: the table point where the object's "
    "centre should end, in each view. List obstacles. Set feasible to false when the instruction cannot be done safely, "
    "for example when the destination is on top of another object or off the table. No metric scale is calibrated.")
JUDGE_SYSTEM = (
    "You check one phase of a pick-and-place by a desk arm with a blue gripper and an orange sponge. You get the second "
    "camera before and after the phase and the front camera after it. Say whether the phase succeeded, why, and what to "
    "try next: continue, retry, shift_outward (jaws farther from the arm base), shift_inward (closer to the base), "
    "lower_more, or ask_human. A local sensor decides success; your reason goes to the log.")


def _jpeg(frame) -> bytes:
    return cv2.imencode(".jpg", frame.image, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


def _local(reason: str) -> dict:
    return {"success": None, "reason": reason, "next": None, "source": "local"}


def _wait(future, timeout: float):
    try:
        return future.result(timeout=timeout)
    except Exception:
        return None


def plan_task(client, instruction: str, frames: dict) -> dict:
    images = [("c922 camera (front, above)", _jpeg(frames["c922"])), ("usb camera (second view)", _jpeg(frames["usb"]))]
    return json.loads(client.vision_json(PLAN_SYSTEM, f"Instruction: {instruction}", images, PLAN_SCHEMA, "arm_task_plan"))


def judge(client, phase: str, before: dict, after: dict) -> dict:
    if client is None:
        return _local("Muse unavailable")
    images = [("usb_before camera", _jpeg(before["usb"])), ("usb_after camera", _jpeg(after["usb"])),
              ("c922_after camera", _jpeg(after["c922"]))]
    try:
        verdict = json.loads(client.vision_json(JUDGE_SYSTEM, f"Phase: {phase}.", images, VERDICT_SCHEMA, "arm_verdict"))
    except Exception as failure:
        return _local(f"Muse failed: {failure}")
    return dict(verdict, source="muse")


def find_object(client, frames: dict, phrase: str) -> dict:
    # The local orange detector first; SAM only for a view where it found nothing.
    found = {}
    for view, frame in frames.items():
        found[view] = locate_object(frame.image)
        if found[view] is not None or client is None:
            continue
        try:
            records = client.segment(frame.jpeg, phrase)
        except Exception:
            records = []
        if records:
            best = max(records, key=lambda r: r.confidence or 0)
            height, width = cv2.imdecode(np.frombuffer(frame.jpeg, np.uint8), cv2.IMREAD_GRAYSCALE).shape
            sx, sy = SIZE[0] / width, SIZE[1] / height
            x0, top, x1, bottom = best.box[0] * sx, best.box[1] * sy, best.box[2] * sx, best.box[3] * sy
            found[view] = {"cx": (x0 + x1) / 2, "cy": (top + bottom) / 2, "top": top, "bottom": bottom,
                           "x0": x0, "x1": x1, "area": (x1 - x0) * (bottom - top)}
    return found


def _at_base(atlas: list, pick_pulses: dict, base: int) -> dict:
    return {v: None if p is None else tuple(p) for v, p in predict_tip(atlas, dict(pick_pulses, base=base)).items()}


def _in_image(point) -> bool:
    return isinstance(point, list) and len(point) == 2 and 0 <= point[0] < SIZE[0] and 0 <= point[1] < SIZE[1]


def _inside(point, box) -> bool:
    return box is not None and box["x0"] <= point[0] <= box["x1"] and box["top"] <= point[1] <= box["bottom"]


def safe_destination(plan: dict | None, pick_pulses: dict, obj: dict, atlas: list) -> dict:
    # Muse's point only chooses the base angle; height and reach stay those of the pick.
    default = _at_base(atlas, pick_pulses, pick_pulses["base"] + DEFAULT_BASE_SHIFT_US)
    if not plan or not plan.get("feasible"):
        return default
    points = plan.get("destination_px") or {}
    if not all(_in_image(points.get(v)) for v in ("c922", "usb")) or any(_inside(points[v], obj.get(v)) for v in points):
        return default
    bases = range(BASE_RANGE_US[0], BASE_RANGE_US[1] + 1, 10)

    def distance(base):
        tips = _at_base(atlas, pick_pulses, base)
        return sum(w * math.dist(tips[v], points[v]) for v, w in (("c922", 0.6), ("usb", 1.0)) if tips[v])
    best = min(bases, key=distance)
    if best in (bases[0], bases[-1]):
        return default
    return _at_base(atlas, pick_pulses, best)


def _draw(frames: dict, obj: dict, destination: dict | None, path: Path):
    tips, tiles = locate_tips(frames), []
    for view in ("c922", "usb"):
        image = frames[view].image.copy()
        box = obj.get(view)
        if box:
            cv2.rectangle(image, (int(box["x0"]), int(box["top"])), (int(box["x1"]), int(box["bottom"])), (0, 140, 255), 4)
        if destination and destination.get(view):
            cv2.drawMarker(image, tuple(int(c) for c in destination[view]), (0, 200, 0), cv2.MARKER_CROSS, 60, 6)
        if tips.get(view):
            cv2.circle(image, tuple(int(c) for c in tips[view]), 22, (0, 255, 255), 5)
        tiles.append(cv2.resize(image, (960, 540)))
    cv2.imwrite(str(path), np.hstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 80])


def run_task(instruction: str, session, cams, atlas: list, client, memory: dict, log_path: Path, choose=None) -> dict:
    began, log_path = time.perf_counter(), Path(log_path)
    log_path.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    log = {"run_id": run_id, "instruction": instruction, "started_at": datetime.now(timezone.utc).isoformat(),
           "phase": "planning", "muse": "unavailable" if client is None else "available",
           "steps": [], "verdicts": [], "plan": None, "object": None, "destination": None}
    pending = []

    def save(**changes):
        log.update(changes, seconds=round(time.perf_counter() - began, 1))
        if client is not None:
            log["meta"] = {"calls": client.budget.calls, "usd": round(client.budget.usd, 4)}
        (log_path / f"{run_id}.json").write_text(json.dumps(log, indent=1) + "\n", encoding="utf-8")

    def finish(ok: bool, reason: str) -> dict:
        for phase, future in pending:
            log["verdicts"].append(dict(_wait(future, JUDGE_TIMEOUT_S) or _local("Muse timed out"), phase=phase))
        _draw(cams.snapshot(), log["object"] or {}, log["destination"], log_path / "latest.jpg")
        save(phase="done", ok=ok, reason=reason)
        return {"ok": ok, "reason": reason, "run_id": run_id, "seconds": log["seconds"]}

    frames = cams.snapshot()
    save()
    planning = POOL.submit(plan_task, client, instruction, frames) if client else None
    obj = find_object(client, frames, OBJECT_PHRASE)
    save(object=obj, phase="grasp")
    if obj.get("usb") is None:
        return finish(False, "object_not_found")

    def advise(offset: int) -> int | None:
        after = cams.snapshot(after=time.perf_counter() + SETTLE_S)
        verdict = _wait(POOL.submit(judge, client, "grasp", frames, after), JUDGE_TIMEOUT_S) or _local("Muse timed out")
        log["verdicts"].append(dict(verdict, phase="grasp_retry"))
        save()
        shift = NEXT_OFFSET.get(verdict.get("next"))
        return None if shift is None else offset + shift

    grasped = grasp(session, cams, atlas, memory, advise=advise if client else None, choose=choose)
    log["steps"].append(dict(grasped, phase="grasp"))
    if not grasped["ok"]:
        return finish(False, f"grasp_{grasped['reason']}")
    if client:
        pending.append(("grasp", POOL.submit(judge, client, "grasp", frames, cams.snapshot())))
    plan = _wait(planning, PLAN_TIMEOUT_S) if planning else None
    destination = safe_destination(plan, grasped["pick_pulses"], obj, atlas)
    save(plan=plan, destination=destination, phase="place")
    before = cams.snapshot()
    placed = place(session, cams, atlas, destination, memory)
    log["steps"].append(dict(placed, phase="place"))
    if client:
        pending.append(("place", POOL.submit(judge, client, "place", before, cams.snapshot())))
    return finish(placed["ok"], "done" if placed["ok"] else f"place_{placed['reason']}")
