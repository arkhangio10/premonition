"""Short repeatability check after a camera change: base and shoulder out and back three times, tip spread per view."""
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, ".")
from premonition.arm_session import ArmSession
from premonition.atlas import look
from premonition.dual_camera import DualCamera

with ArmSession("jetson-usb", Path("runs")) as arm:
    cams = DualCamera("jetson-usb"); cams.start()
    try:
        home = dict(arm.positions); tips = [look(cams)]
        for joint in ("base", "shoulder", "base"):
            arm.move({joint: home[joint] + 60}); arm.settle_move({joint: home[joint]}); tips.append(look(cams))
        for view in ("c922", "usb"):
            pts = np.array([t[view] for t in tips if t[view]], float)
            print(view, len(pts), "of", len(tips), "std px", round(float(np.sqrt(pts.var(axis=0).sum())), 2), pts.round(1).tolist())
    finally:
        cams.close()
