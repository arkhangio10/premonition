"""Read-only: registers, arm processes and one photo per camera, with the detected tip drawn."""
import base64, json, subprocess, sys, time, uuid
from pathlib import Path
import cv2, numpy as np
sys.path.insert(0, ".")
from premonition.jetson import _script, check_connection, inspect_system, read_commanded_pulses, ssh_argv
from premonition.visual_servo import BASE_PX, locate_tip
out, tag = Path(sys.argv[1]), sys.argv[2]
host = "jetson-usb"
print("connection:", check_connection(host))
print("registers:", json.dumps(read_commanded_pulses(host)), "| arm_processes:", inspect_system(host)["arm_processes"])
tips = {}
for device, view, reads in ((0, "c922", 8), (1, "usb", 30)):
    r = subprocess.run(ssh_argv(host, f"python3 - --token {uuid.uuid4().hex} --device {device} --reads {reads}"),
                       input=_script("capture_once.py"), capture_output=True, timeout=60)
    reply = json.loads(r.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
    if not reply.get("ok"):
        print(view, "error:", reply.get("error")); continue
    path = out / f"{tag}_{view}.jpg"
    path.write_bytes(base64.b64decode(reply["jpeg_b64"]))
    image = cv2.imread(str(path))
    tip = locate_tip(image, BASE_PX[view])
    tips[view] = tip
    print(view, reply["width"], "x", reply["height"], "good_reads", reply["good_reads"], "tip", tip and tuple(round(v) for v in tip))
    vis = image.copy()
    if tip:
        cv2.circle(vis, tuple(round(v) for v in tip), 22, (0, 255, 255), 4)
    cv2.circle(vis, BASE_PX[view], 22, (255, 0, 255), 4)
    cv2.imwrite(str(out / f"{tag}_{view}_review.jpg"), cv2.resize(vis, (960, 540)), [cv2.IMWRITE_JPEG_QUALITY, 85])
(out / f"{tag}_tips.json").write_text(json.dumps(tips), encoding="utf-8")
