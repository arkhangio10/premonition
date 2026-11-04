"""Extend the atlas to base 1600/1650 in the high rows only (the sponge stays on the table below)."""
import json, sys
from pathlib import Path
sys.path.insert(0, ".")
from premonition.arm_session import ArmSession
from premonition.atlas import merge_scans, scan, travel
from premonition.dual_camera import DualCamera
CAL = Path("runs/real/calibration")
EXT = {"base": [1600, 1650], "shoulder": [1640, 1560], "elbow": [2050, 2170, 2290]}
main = json.loads((CAL / "capabilities.json").read_text(encoding="utf-8"))
(CAL / "capabilities_before_extension_20261103.json").write_text(json.dumps(main, indent=1) + "\n", encoding="utf-8")
with ArmSession("jetson-usb", Path("runs")) as arm:
    cams = DualCamera("jetson-usb"); cams.start()
    try:
        travel(arm, {"shoulder": 1640})
        a = scan(arm, cams, EXT, CAL / "capabilities_ext_pass1.json")
        travel(arm, {"shoulder": 1640})
        b = scan(arm, cams, EXT, CAL / "capabilities_ext_pass2.json")
    finally:
        cams.close()
    print("final", arm.positions)
assert a["stop"] is None and b["stop"] is None, (a["stop"], b["stop"])
ext = merge_scans(a["atlas"], b["atlas"])
main["atlas"] += ext
main["extension"] = {"grid": EXT, "passes": ["capabilities_ext_pass1.json", "capabilities_ext_pass2.json"],
                     "repeatability_px": [a["repeatability_px"], b["repeatability_px"]], "stalls": a["stalls"] + b["stalls"]}
(CAL / "capabilities.json").write_text(json.dumps(main, indent=1) + "\n", encoding="utf-8")
print("added", len(ext), "dropped", {v: sum(s["tip"][v] is None for s in ext) for v in ("c922", "usb")}, "repeat", main["extension"]["repeatability_px"])
for s in ext: print(s["pulses"], s["tip"])
