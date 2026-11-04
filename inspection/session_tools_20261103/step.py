import json, subprocess, sys, threading, time, uuid
from datetime import datetime, timezone
from pathlib import Path
import cv2, httpx, numpy as np
sys.path.insert(0, ".")
from inspection.approach_probe_20261102 import build_review_command
from premonition.jetson import read_commanded_pulses

scratch, name, joint, target, purpose = Path(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
duration = float(sys.argv[6]) if len(sys.argv) > 6 else 4.0
CAL = Path("runs/real/calibration"); BASE = "http://127.0.0.1:8765"
review_name = f"teaching_step_{name}.json"
assert not (CAL/"motion_hold.json").exists(), "hold present"
assert not (CAL/review_name).exists(), "review already exists"
cap = json.loads((scratch/"current_capture.json").read_text(encoding="utf-8"))
c = httpx.Client(base_url=BASE, timeout=60)
assert c.get("/api/calibration").json()["capture"]["sha256"] == cap["sha256"], "capture changed"
before = read_commanded_pulses("jetson-usb")
statement = sys.argv[7] if len(sys.argv) > 7 else "continúa con lo que dice STATUS.md / la fuente esta enchufada, que pasas por que no puedes continuar"
review = {"status": "prepared", "prepared_at": datetime.now(timezone.utc).isoformat(),
          "base_fixed_operator_confirmed": True, "table_prepared_operator_confirmed": True,
          "authorization": f"Operator message: '{statement}'. Operator chose to restart at last pose and to move the sponge in front of the arm. Capped single-joint step; each before-photo reviewed.",
          "expected_readback": before, "purpose": purpose,
          "reviewed_capture_file": cap["file"], "reviewed_capture_sha256": cap["sha256"],
          "command": {"id": 1, "cmd": "move", "targets": dict(before["commanded_us"], **{joint: target}), "duration": duration}}
build_review_command(before, review)
(CAL/review_name).write_text(json.dumps(review, indent=2)+"\n", encoding="utf-8")

token = uuid.uuid4().hex; frames = []
def reader():
    buf = b""
    try:
        with httpx.stream("GET", f"{BASE}/api/camera/live.mjpg?token={token}", timeout=None) as r:
            for chunk in r.iter_bytes():
                buf += chunk
                while True:
                    a, b = buf.find(b"\xff\xd8"), buf.find(b"\xff\xd9")
                    if a < 0 or b < a: break
                    frames.append((time.time(), buf[a:b+2])); buf = buf[b+2:]
    except Exception:
        pass
threading.Thread(target=reader, daemon=True).start()
end = time.time()+16
while time.time() < end:
    s = c.get("/api/camera/live/status").json()
    if s.get("token") == token and s.get("active"): break
    time.sleep(.3)
else:
    raise SystemExit("preview not active; nothing moved")
time.sleep(2)
age = time.time()-(Path("runs/real/captures")/cap["file"]).stat().st_mtime
print("photo age s:", round(age)); assert age < 112, "photo too old; nothing moved"
t0 = time.time()
r = subprocess.run([sys.executable, "-m", "inspection.approach_probe_20261102", "--review", review_name], capture_output=True, text=True, timeout=60)
t1 = time.time()
print("probe rc:", r.returncode, "| took s:", round(t1-t0, 1))
print(r.stdout[-420:].replace("\n", " ")); print(r.stderr[-400:])
time.sleep(4)
print("stop preview:", c.post("/api/camera/live/stop", json={"token": token}).status_code)
after = read_commanded_pulses("jetson-usb")
print("before:", before["commanded_us"]); print("after: ", after["commanded_us"], after["mode1"], after["prescale"])
gray = [(t, cv2.imdecode(np.frombuffer(j, np.uint8), cv2.IMREAD_GRAYSCALE)) for t, j in frames]
gray = [(t, g) for t, g in gray if g is not None]
print("frames:", len(gray))
roi = lambda g: g[130:470, 380:820]
d = [(gray[i+1][0], float(cv2.absdiff(roi(gray[i][1]), roi(gray[i+1][1])).mean())) for i in range(len(gray)-1)]
bins = {}
for t, v in d: bins.setdefault(int(t-t0), []).append(v)
print("diff per second (t=0 at probe start):", {k: round(max(v), 2) for k, v in sorted(bins.items())})
pre = [v for t, v in d if t < t0]; post = [v for t, v in d if t > t1+0.5]
print("baseline mean", round(np.mean(pre), 3), "max", round(max(pre), 3), "| settled mean", round(np.mean(post), 3), "max", round(max(post), 3))
a, b = roi(gray[0][1]), roi(gray[-1][1])
print("first-last ROI mean diff:", round(float(cv2.absdiff(a, b).mean()), 2), "| phase shift:", tuple(round(x, 2) for x in cv2.phaseCorrelate(np.float32(a), np.float32(b))[0]))

