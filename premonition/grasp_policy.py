from dataclasses import asdict, dataclass
from itertools import product

import numpy as np


@dataclass(frozen=True)
class GraspParams:
    offset_usb_x: int = 0
    depth_px: int = 60
    max_steps: int = 3
    grip_open_us: int = 1850
    elbow_min_us: int = 2050


DEFAULT_PARAMS = GraspParams()

_PROFILES = ((60, 4, 1850), (90, 5, 1940))
ARMS = tuple(GraspParams(offset, depth, steps, grip, elbow)
             for offset, (depth, steps, grip), elbow in product((0, -15, -30, 15, 30), _PROFILES, (2050, 2170)))

TOWARD = {
    "jaws_on_top": (("offset_usb_x", -1), ("grip_open_us", 1)),
    "pushed": (("offset_usb_x", -1),),
    "closed_on_air": (("offset_usb_x", 1),),
    "too_shallow": (("depth_px", 1), ("max_steps", 1)),
    "slipped": (("depth_px", 1),),
}

HELP = {
    "pushed": "The jaws push the sponge away instead of closing on it. Move it a bit closer to the arm or turn it so its thin side faces the jaws.",
    "object_lost": "The sponge left the view during the lift. Put it back on the table inside the camera view.",
    "jaws_on_top": "The jaws land on top of the sponge. Turn it so its thin side sits between the jaws, or move it closer to the arm.",
    "too_shallow": "The jaws close above the sponge. Place it where the arm can reach lower, or make it easier to grip.",
    "slipped": "The sponge slips out of the jaws while lifting. Turn it so a firmer part sits between the jaws.",
    "closed_on_air": "The jaws close beside the sponge. Move it toward the arm or center it in front of the jaws.",
    "not_lifted": "The sponge did not come off the table. Reposition it and tell me which side the jaws should go.",
    "reach_failed": "The arm could not line up over the sponge in both cameras. Move it a little toward the middle of the table, inside the area the scan covered.",
}


def classify(attempt: dict) -> str:
    if attempt["lifted"]:
        return "lifted"
    stop = attempt["descent_stop"]
    if stop == "pushed":
        return "pushed"
    resting, after = attempt["resting"], attempt["after_lift"]
    if after is None or after["bottom"] - after["top"] < 0.6 * (resting["bottom"] - resting["top"]):
        # Right after the lift the gripper can hide the sponge from the side USB: lost only if the C922 lost it too.
        return "object_lost" if attempt.get("after_lift_c922") is None else "not_lifted"
    depth = attempt["params"]["depth_px"]
    tip_end, rise = attempt["tip_end"], attempt["rise_px"]
    tip_y = None if tip_end is None else tip_end[1]
    if stop == "stalled" and tip_y is not None and tip_y < resting["top"] + depth / 2:
        return "jaws_on_top"
    if stop == "cap" and tip_y is not None and tip_y < resting["top"] + depth:
        return "too_shallow"
    if rise is not None and 5 <= rise < 25:
        return "slipped"
    if rise is not None and rise < 5 and tip_y is not None and tip_y >= resting["top"] + depth:
        return "closed_on_air"
    return "not_lifted"


def posterior(attempts: list[dict], arm: GraspParams) -> tuple[float, float]:
    alpha, beta = (2.0, 1.0) if arm.depth_px == 90 else (1.0, 1.0)
    for a in attempts:
        if a.get("legacy") or a.get("skill", "grasp") != "grasp" or a["params"] != asdict(arm):
            continue
        if a["lifted"] or a["class"] == "lifted":
            alpha += 1
        else:
            beta += 1
    return alpha, beta


def _moves_toward(arm: GraspParams, last_params: dict, directions) -> bool:
    return any((getattr(arm, field) - last_params[field]) * sign > 0 for field, sign in directions)


def make_chooser(memory: dict, rng: np.random.Generator, repeat_success: bool = False):
    successful = tuple(arm for arm in ARMS if any(
        not a.get("legacy") and a.get("skill", "grasp") == "grasp"
        and (a.get("lifted") is True or a.get("class") == "lifted") and a.get("params") == asdict(arm)
        for a in memory.get("attempts", []))) if repeat_success else ()
    def confidence(arm):
        alpha, beta = posterior(memory["attempts"], arm)
        return alpha / (alpha + beta)
    def choose(attempts: list[dict]) -> GraspParams:
        if not attempts and successful:
            return max(successful, key=confidence)
        pool = ARMS
        if attempts:
            last = attempts[-1]
            last_params = last["params"]
            directions = TOWARD.get(last["class"], ())
            if last["class"] == "not_lifted" and last.get("muse_offset") is not None:
                sign = int(np.sign(last["muse_offset"] - last_params["offset_usb_x"]))
                directions = (("offset_usb_x", sign),) if sign else ()
            pool = tuple(a for a in ARMS if a != GraspParams(**last_params))
            toward = tuple(a for a in pool if _moves_toward(a, last_params, directions))
            if directions and toward:
                pool = toward
        scores = [rng.beta(*posterior(memory["attempts"], arm)) for arm in pool]
        return pool[int(np.argmax(scores))]
    return choose


def upgrade_memory(memory: dict) -> dict:
    upgraded = {k: v for k, v in memory.items() if k != "failures"}
    upgraded["attempts"] = list(memory.get("attempts", [])) + [
        {"t": f["t"], "skill": "grasp", "params": {"offset_usb_x": f["offset"]}, "class": "unclassified",
         "lifted": False, "legacy": True}
        for f in memory.get("failures", [])]
    return upgraded
