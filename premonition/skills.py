"""Grasp and place, each judged by local two-camera checks; failed grasps retry at shifted points or with the
parameters the grasp policy chooses."""
import json
import math
import time
from dataclasses import asdict, replace
from pathlib import Path

from .arm_session import MAX_DELTA_US
from .atlas import SETTLE_S, locate_tips, stalled
from .grasp_policy import DEFAULT_PARAMS, HELP, classify, upgrade_memory
from .reach import reach
from .scene_detect import locate_object

HOVER_PX = 60
GRIP_OPEN_US = 1850
GRIP_CLOSED_US = 1382
DESCENT_US = 60
LIFT_STEPS = 3
GRIP_S = 1.5
RETRY_OFFSETS = (0, -15, 15)
MAX_DESCENT_STEPS = 3
PUSH_PX = 20
# The grasp that worked hangs the gripper almost vertical (elbow ~2290, pitch 1182); a lower elbow tilts it and
# reaches farther from the base.
GRASP_ELBOW_MIN_US = 2050
SERVO_JOINTS = ("base", "shoulder", "elbow")
# The open jaws straddle the edge with ~2 cm to spare, so 25 px in the USB is still a valid grasp point.
REACH_TOLERANCE = {"c922": 30, "usb": 25}
MEMORY_FILE = "real/calibration/skill_memory.json"
LEARN_ATTEMPTS = 5
MAX_GRASP_S = 300


def load_memory(root: Path) -> dict:
    path = Path(root) / MEMORY_FILE
    if path.exists():
        return upgrade_memory(json.loads(path.read_text(encoding="utf-8")))
    return {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}


def save_memory(root: Path, memory: dict):
    path = Path(root) / MEMORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(memory, indent=1) + "\n", encoding="utf-8")


def observe(cams) -> tuple[dict, dict]:
    frames = cams.snapshot(after=time.perf_counter() + SETTLE_S)
    return locate_tips(frames), {view: locate_object(frame.image) for view, frame in frames.items()}


def _shift(a: dict, b: dict) -> float:
    return math.hypot(b["cx"] - a["cx"], b["cy"] - a["cy"])


def lifted(before: dict, after: dict, tip_rise: float | None = None) -> bool:
    # With the tip's own rise known, the object has to follow 40 % of it: a sponge held by one end pivots on the other
    # and its top rose half as much as the tip (4 Nov); one that is not held stays or sinks.
    need = 25 if tip_rise is None or tip_rise < 10 else max(10, 0.4 * tip_rise)
    if not before.get("usb") or not after.get("usb") or before["usb"]["top"] - after["usb"]["top"] < need:
        return False
    return not (before.get("c922") and after.get("c922")) or _shift(before["c922"], after["c922"]) >= 10


def released(before: dict, after: dict) -> bool:
    # Released means it stayed down: a sponge let go above the table falls and shifts, one stuck to a jaw rises with it.
    if not before.get("usb") or not after.get("usb"):
        return False
    return all(before[v]["top"] - after[v]["top"] < 10 for v in ("c922", "usb") if before.get(v) and after.get(v))


def in_contact(object_drop_px: float, tip_drop_px: float) -> bool:
    return object_drop_px < 0.5 * tip_drop_px


def grasp_target(obj: dict, memory: dict) -> dict:
    # The front C922 pins only the side (the base turn); its y mixes height and depth, so the side USB sets the hover.
    # On 4 Nov a C922 hover 30 px over the sponge's front edge sat 100 px from where the USB hover put the tip.
    usb, c922 = obj["usb"], obj.get("c922")
    return {"usb": (usb["x0"] + 15 + memory["grasp_offset_usb_x"], usb["top"] - HOVER_PX),
            "c922": None if c922 is None else (c922["x0"] + 0.3 * (c922["x1"] - c922["x0"]), None)}


def _vertical(atlas: list, elbow_min_us: int = GRASP_ELBOW_MIN_US) -> list:
    return [s for s in atlas if s["pulses"]["elbow"] >= elbow_min_us]


def _descend(session, cams, stop, max_steps: int) -> list[dict]:
    # Shoulder down one step at a time; a blocked tip or a lost view also ends the descent. The last step says why.
    now, steps = observe(cams), []
    if now[1].get("usb") is None or (now[0].get("usb") is None and now[0].get("c922") is None):
        return steps
    for _ in range(max_steps):
        session.move({"shoulder": session.positions["shoulder"] - DESCENT_US})
        before, now = now, observe(cams)
        steps.append({"shoulder": session.positions["shoulder"], "tip": now[0].get("usb"), "object": now[1].get("usb")})
        # Open jaws that straddle the object put one jaw behind it: a USB tip hidden while the C922 still sees one is
        # expected there, so the descent goes on (to the step cap, as depth cannot be read without the USB tip).
        hidden = now[0].get("usb") is None and now[0].get("c922") is not None
        reason = ("lost" if now[1].get("usb") is None or (now[0].get("usb") is None and not hidden)
                  else "stalled" if stalled(before[0], now[0], DESCENT_US) else stop(before, now))
        if reason:
            steps[-1]["stop"] = reason
            return steps
    steps[-1]["stop"] = "cap"
    return steps


def _pushed(resting: dict, now: dict) -> bool:
    # Only the inner side stays clean: the gripper hides the outer corner and orange glints appear under the jaws.
    return abs(now["x1"] - resting["x1"]) >= PUSH_PX


def _grip(session, target: int):
    while session.positions["gripper"] != target:
        delta = max(-MAX_DELTA_US, min(MAX_DELTA_US, target - session.positions["gripper"]))
        session.move({"gripper": session.positions["gripper"] + delta}, duration=max(GRIP_S, abs(delta) / 150))


def _lift(session, steps: int):
    for _ in range(steps):
        session.move({"shoulder": session.positions["shoulder"] + DESCENT_US})


def _result(ok: bool, reason: str, attempts: int, began: float, **extra) -> dict:
    return {"ok": ok, "reason": reason, "attempts": attempts, "seconds": round(time.perf_counter() - began, 1), **extra}


def grasp(session, cams, atlas, memory: dict, advise=None, choose=None, max_attempts=None, photo=None) -> dict:
    # advise(offset) may return the next offset (Muse); None keeps the local sequence. With choose(tries) the grasp
    # policy picks every attempt's parameters, Muse's offset only goes to the attempt's record and the policy stops.
    began, learned, descents, tries = time.perf_counter(), memory["grasp_offset_usb_x"], [], []
    cap = len(RETRY_OFFSETS) if choose is None else LEARN_ATTEMPTS
    limit = min(max_attempts or cap, cap)
    offset = learned + RETRY_OFFSETS[0]
    for attempt in range(1, limit + 1):
        started = time.perf_counter()
        if choose is not None and attempt > 1 and time.perf_counter() - began > MAX_GRASP_S:
            return _result(False, "time_limit", attempt - 1, began, descents=descents, tries=tries)
        params = replace(DEFAULT_PARAMS, offset_usb_x=offset) if choose is None else choose(tries)
        _, objects = observe(cams)
        if objects.get("usb") is None:
            return _result(False, "object_not_found", attempt, began, descents=descents, tries=tries)
        moved = reach(session, cams, _vertical(atlas, params.elbow_min_us),
                      grasp_target(objects, dict(memory, grasp_offset_usb_x=params.offset_usb_x)),
                      joints=SERVO_JOINTS, tolerance=REACH_TOLERANCE)
        if not moved["ok"] and choose is None:
            return _result(False, f"reach_{moved['reason']}", attempt, began, descents=descents, tries=tries)
        if not moved["ok"]:
            # The policy learns from a failed approach too: recorded, never repeated with the same params.
            record = {"t": time.time(), "skill": "grasp", "params": asdict(params), "lifted": False, "class": "reach_failed",
                      "reach": moved["reason"], "reach_error_px": moved["error_px"], "reach_pulses": dict(moved["pulses"]),
                      "muse_offset": None, "legacy": False,
                      "seconds": round(time.perf_counter() - started, 1)}
            tries.append(record)
            memory.setdefault("attempts", []).append(record)
            if [t["class"] for t in tries[-3:]] == ["reach_failed"] * 3:
                break
            continue
        _grip(session, params.grip_open_us)
        resting = objects["usb"]
        # A resting object that slides sideways is being pushed: stop before it falls over.
        # The inner jaw sinks into the soft top while the outer one goes down outside the edge.
        steps = _descend(session, cams, lambda before, now: "pushed" if _pushed(resting, now[1]["usb"]) else
                         "reached" if now[0]["usb"] and now[0]["usb"][1] >= resting["top"] + params.depth_px else None,
                         params.max_steps)
        descents.append(steps)
        if photo:
            photo(attempt, "descent")
        _grip(session, GRIP_CLOSED_US)
        pick = dict(session.positions)
        tips_before, before = observe(cams)
        # Near the X one shoulder step lifts the tip only 13-20 px: the policy judges two steps against the tip's rise.
        judged = 1 if choose is None else 2
        _lift(session, judged)
        tips_after, after = observe(cams)
        if photo:
            photo(attempt, "lift")
        seen = before.get("usb") and after.get("usb")
        tip_rise = (tips_before["usb"][1] - tips_after["usb"][1]
                    if choose is not None and tips_before.get("usb") and tips_after.get("usb") else None)
        record = {"t": time.time(), "skill": "grasp", "params": asdict(params), "lifted": lifted(before, after, tip_rise),
                  "tip_rise_px": tip_rise,
                  "descent_stop": steps[-1]["stop"] if steps else "lost",
                  "tip_end": steps[-1]["tip"] if steps else None, "resting": resting, "after_lift": after.get("usb"),
                  "after_lift_c922": after.get("c922"),
                  "rise_px": before["usb"]["top"] - after["usb"]["top"] if seen else None,
                  "muse_offset": None, "legacy": False}
        record["class"] = classify(record)
        tries.append(record)
        memory.setdefault("attempts", []).append(record)
        if record["lifted"]:
            _lift(session, LIFT_STEPS - judged)
            record["seconds"] = round(time.perf_counter() - started, 1)
            memory["grasp_offset_usb_x"] = params.offset_usb_x
            memory["successes"] = memory.get("successes", 0) + 1
            return _result(True, "lifted", attempt, began, pick_pulses=pick, descents=descents, tries=tries)
        repeated = [t["class"] for t in tries[-3:]] == [record["class"]] * 3
        stop = choose is not None and (record["class"] == "object_lost" or repeated)
        if advise and not stop and attempt < limit and (choose is None or record["class"] == "not_lifted"):
            record["muse_offset"] = advise(params.offset_usb_x)
        _grip(session, GRIP_OPEN_US)
        # With the judging lift steps, the arm climbs back at least as far as it descended.
        _lift(session, 2 if choose is None else max(1, len(steps) - 2))
        record["seconds"] = round(time.perf_counter() - started, 1)
        if stop:
            break
        if choose is None and attempt < limit:
            offset = learned + RETRY_OFFSETS[attempt] if record["muse_offset"] is None else record["muse_offset"]
    return _result(False, "ask_human", attempt, began, descents=descents, tries=tries, help=HELP[record["class"]])


def place(session, cams, atlas, destination: dict, memory: dict) -> dict:
    began = time.perf_counter()
    c922 = destination.get("c922")
    target = {"usb": (destination["usb"][0], destination["usb"][1] - HOVER_PX),
              "c922": None if c922 is None else (c922[0], None)}
    moved = reach(session, cams, _vertical(atlas), target, joints=SERVO_JOINTS, tolerance=REACH_TOLERANCE)
    if not moved["ok"]:
        return _result(False, f"reach_{moved['reason']}", 1, began)

    def contact(before, now):
        if before[0]["usb"] and now[0]["usb"] and in_contact(now[1]["usb"]["top"] - before[1]["usb"]["top"], now[0]["usb"][1] - before[0]["usb"][1]):
            return "contact"
        return None
    _descend(session, cams, contact, MAX_DESCENT_STEPS)
    _, before = observe(cams)
    _grip(session, GRIP_OPEN_US)
    _lift(session, LIFT_STEPS)
    _, after = observe(cams)
    reason = "placed" if released(before, after) else "not_released"
    memory.setdefault("attempts", []).append({"t": time.time(), "skill": "place", "class": reason, "legacy": False})
    return _result(reason == "placed", reason, 1, began)
