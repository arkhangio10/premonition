"""Persistent inhibition of supervised motion helpers after an observed physical fault."""
from pathlib import Path


class MotionHeld(RuntimeError):
    pass


def require_no_motion_hold(root: Path):
    # Presence alone blocks motion, including malformed or partially written incident data.
    path=Path(root)/"real/calibration/motion_hold.json"
    if path.exists():
        raise MotionHeld("Physical fault hold: motion is suspended. Resolve and document the physical cause before clearing motion_hold.json.")
