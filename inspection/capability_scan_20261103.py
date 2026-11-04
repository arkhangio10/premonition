"""Physical capability scan over SCAN_GRID, run twice and merged: writes capabilities.json and a control image."""
import json
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from premonition.arm_session import ArmSession
from premonition.atlas import GRASP_WRIST, SCAN_GRID, detector_report, merge_scans, scan, travel
from premonition.dual_camera import DualCamera
from premonition.view_check import check_views, save_reference

HOST = "jetson-usb"
ROOT = Path("runs")
OUT = ROOT / "real/calibration/capabilities.json"
CONTROL = ROOT / "real/calibration/capabilities_control.jpg"
FRAMES = ROOT / "real/calibration/scan_frames"


def draw(report: dict, frames: dict, path: Path):
    tiles = []
    for view in ("c922", "usb"):
        image = frames[view].image.copy()
        for sample in report["atlas"]:
            if sample["tip"][view]:
                cv2.circle(image, tuple(round(v) for v in sample["tip"][view]), 9, (0, 255, 255), -1)
        for stall in report["stalls"]:
            if stall["tip"][view]:
                cv2.circle(image, tuple(round(v) for v in stall["tip"][view]), 14, (0, 0, 255), 3)
        tiles.append(cv2.resize(image, (960, 540)))
    cv2.imwrite(str(path), np.hstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 85])


def main():
    with ArmSession(HOST, ROOT) as arm:
        cams = DualCamera(HOST)
        cams.start()
        try:
            print(f"live view: http://127.0.0.1:{cams.serve()}", flush=True)
            print(json.dumps(check_views(ROOT, cams.snapshot()), indent=1), flush=True)
            travel(arm, dict(GRASP_WRIST, shoulder=SCAN_GRID["shoulder"][0]))
            frames = FRAMES / datetime.now().strftime("%Y%m%d-%H%M%S")
            began = time.perf_counter()
            first = scan(arm, cams, SCAN_GRID, OUT.with_name("capabilities_pass1.json"), frames / "pass1")
            travel(arm, {"shoulder": SCAN_GRID["shoulder"][0]})
            report = scan(arm, cams, SCAN_GRID, OUT.with_name("capabilities_pass2.json"), frames / "pass2")
            seconds = time.perf_counter() - began
            if first["stop"] is None and report["stop"] is None:
                report.update(atlas=merge_scans(first["atlas"], report["atlas"]), repeatability_px_pass1=first["repeatability_px"],
                              detector_report=detector_report(first["atlas"], report["atlas"]),
                              merged_from=["capabilities_pass1.json", "capabilities_pass2.json"])
                save_reference(ROOT, cams.snapshot())
            OUT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
            draw(report, cams.snapshot(), CONTROL)
        finally:
            cams.close()
        dropped = {v: sum(s["tip"][v] is None for s in report["atlas"]) for v in ("c922", "usb")}
        print(json.dumps({"samples": len(report["atlas"]), "dropped": dropped, "stalls": len(report["stalls"]) + len(first["stalls"]),
                          "stop": [first["stop"], report["stop"]],
                          "seconds": round(seconds, 1), "move_s_mean": report["move_s_mean"],
                          "repeatability_px": report["repeatability_px"], "detector_report": report.get("detector_report"), "final": arm.positions}))


if __name__ == "__main__":
    main()
