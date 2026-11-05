"""Grasp then place at the approved default destination, with the live view on :8767.
--learn lets the grasp policy choose each attempt."""
import json, sys, time
from pathlib import Path
import cv2, numpy as np
sys.path.insert(0, ".")
from premonition.arm_session import ArmSession
from premonition.atlas import configure_tip_detector, predict_tip, travel
from premonition.autonomy import safe_destination
from premonition.dual_camera import DualCamera
from premonition.grasp_policy import make_chooser
from premonition.skills import grasp, load_memory, observe, place, save_memory
from premonition.view_check import check_views, shift_atlas
ROOT = Path("runs")
capabilities = json.loads((ROOT / "real/calibration/capabilities.json").read_text(encoding="utf-8"))
configure_tip_detector(capabilities)
atlas = capabilities["atlas"]
memory = load_memory(ROOT)

def evidence(cams, name):
    f = cams.snapshot(after=time.perf_counter() + 0.4)
    cv2.imwrite(f"inspection/{name}.jpg", np.hstack([cv2.resize(f[v].image, (960, 540)) for v in ("c922", "usb")]),
                [cv2.IMWRITE_JPEG_QUALITY, 85])

with ArmSession("jetson-usb", ROOT) as arm:
    cams = DualCamera("jetson-usb"); cams.start()
    print("live view: http://127.0.0.1:%d" % cams.serve(), flush=True); time.sleep(10)
    try:
        check = check_views(ROOT, cams.snapshot())
        print("views", json.dumps(check), flush=True)
        # A small shift measured on the table tag (the USB mount creeps ~3 px over a night) is followed, not rescanned:
        # check_views already moved BASE_PX, the atlas follows here, and reach closes the loop on live tips.
        small = all(v["decision"] == "still" or (v["decision"] == "rebase" and v["method"] == "marker" and v["moved_px"] <= 10)
                    for v in check["views"].values())
        if check["action"] not in ("still", "no_reference") and not small:
            sys.exit("views moved: rescan with python -m inspection.capability_scan_20261103 (sponge off the table)")
        for view, shift in check["views"].items():
            if shift["decision"] == "rebase":
                atlas = shift_atlas(atlas, view, shift["matrix"])
        began, run = time.perf_counter(), time.strftime("%H%M%S")
        travel(arm, {"shoulder": 1640})
        tips, objects = observe(cams)
        print("start tips", tips, "object", objects)
        g = grasp(arm, cams, atlas, memory,
                  choose=make_chooser(memory, np.random.default_rng()) if "--learn" in sys.argv else None,
                  photo=lambda attempt, moment: evidence(cams, f"grasp-{run}-try{attempt}-{moment}-20261103"))
        print("grasp", json.dumps(g)); save_memory(ROOT, memory)
        evidence(cams, "autonomy-grasp-20261103")
        if g["ok"]:
            pick = g["pick_pulses"]
            destination = safe_destination(None, pick, {}, atlas)
            print("destination", destination)
            p = place(arm, cams, atlas, destination, memory)
            print("place", json.dumps(p)); save_memory(ROOT, memory)
            evidence(cams, "autonomy-place-20261103")
        print("cycle s", round(time.perf_counter() - began, 1), "final", arm.positions)
    finally:
        save_memory(ROOT, memory)
        cams.close()
