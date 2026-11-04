"""Record operator-observed poses from stable commanded pulses. Never moves the arm."""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .first_motion import AUTO_INCREMENT, PRESCALE_50HZ, SLEEP
from .models import Cell


class PoseNotReady(ValueError):
    pass


def pose_blockers(reading: dict | None, cell: Cell) -> list[str]:
    if reading is None:
        return ["Check the arm to read its controller."]
    blockers = []
    if reading.get("mode1", SLEEP) & SLEEP:
        blockers.append("The controller is asleep.")
    if reading.get("prescale") != PRESCALE_50HZ:
        blockers.append("The controller is not configured for the expected 50 Hz PWM.")
    if not reading.get("mode1", 0) & AUTO_INCREMENT:
        blockers.append("The controller is not ready for the existing motion protocol.")
    pulses = reading.get("commanded_us", {})
    if set(pulses) != set(cell.joints):
        blockers.append("The reading must contain all six joints.")
    else:
        for joint in cell.joints:
            pulse = pulses[joint]
            if pulse is None:
                blockers.append(f"{joint}: output is off.")
            elif type(pulse) is not int or not cell.envelope_us[joint][0] <= pulse <= cell.envelope_us[joint][1]:
                blockers.append(f"{joint}: commanded pulse is outside the configured envelope.")
    return blockers


def load_poses(root: Path) -> list[dict]:
    path = Path(root) / "real" / "calibration" / "poses.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def record_pose(root: Path, cell: Cell, name: str, expected: dict,
                first: dict, second: dict, operator_observed: bool) -> dict:
    if not operator_observed:
        raise PoseNotReady("Confirm that you observed this pose on the real arm.")
    name = name.strip()
    if not name or len(name) > 60 or any(ord(c) < 32 for c in name):
        raise PoseNotReady("Use a pose name with 1–60 visible characters.")
    blockers = pose_blockers(first, cell) + pose_blockers(second, cell)
    if blockers:
        raise PoseNotReady(" ".join(dict.fromkeys(blockers)))
    if first != second:
        raise PoseNotReady("The controller changed during recording. Check the pose again.")
    if expected != second["commanded_us"]:
        raise PoseNotReady("The pulses changed since your last check. Check the arm again.")
    poses = load_poses(root)
    if any(pose["name"].casefold() == name.casefold() for pose in poses):
        raise PoseNotReady("That pose name already exists. Choose a new name.")
    pose = {"id": uuid.uuid4().hex, "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "targets_us": dict(second["commanded_us"]), "source": "commanded_pulses",
            "operator_observed": True, "cell_id": cell.cell_id,
            "envelope_us": cell.model_dump()["envelope_us"],
            "note": "Operator-observed pose. Pulses are commands, not measured joint angles. No route validated."}
    path = Path(root) / "real" / "calibration" / "poses.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"poses-{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(poses + [pose], ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return pose
