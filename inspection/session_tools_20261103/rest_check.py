"""Camera-only: record a few seconds of live preview and measure jitter of the gripper region."""
import sys, threading, time, uuid
import cv2, httpx, numpy as np
BASE = "http://127.0.0.1:8765"
seconds, x, y = float(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])  # tip in 1920x1080 coords
c = httpx.Client(base_url=BASE, timeout=30)
live = c.get("/api/camera/live/status").json()
if live.get("running"):
    c.post("/api/camera/live/stop", json={"token": live["token"]})
token, frames = uuid.uuid4().hex, []
def reader():
    buf = b""
    try:
        with httpx.stream("GET", f"{BASE}/api/camera/live.mjpg?token={token}", timeout=None) as r:
            for chunk in r.iter_bytes():
                buf += chunk
                while True:
                    a, b = buf.find(b"\xff\xd8"), buf.find(b"\xff\xd9")
                    if a < 0 or b < a: break
                    frames.append((time.time(), buf[a:b + 2])); buf = buf[b + 2:]
    except Exception:
        pass
threading.Thread(target=reader, daemon=True).start()
end = time.time() + 16
while time.time() < end and not c.get("/api/camera/live/status").json().get("active"):
    time.sleep(.3)
time.sleep(1); start = len(frames); time.sleep(seconds)
c.post("/api/camera/live/stop", json={"token": token})
gray = [cv2.imdecode(np.frombuffer(j, np.uint8), cv2.IMREAD_GRAYSCALE) for _, j in frames[start:]]
gray = [g for g in gray if g is not None]
h, w = gray[0].shape; sx, sy = w / 1920, h / 1080
roi = lambda g: np.float32(g[max(0, int((y - 120) * sy)):int((y + 120) * sy), max(0, int((x - 160) * sx)):int((x + 160) * sx)])
ref = roi(gray[0])
shifts = np.array([cv2.phaseCorrelate(ref, roi(g))[0] for g in gray[1:]]) / sx
print("frames", len(gray), "size", (w, h), "| tip shift vs first frame in full-res px: max", round(float(np.abs(shifts).max()), 2),
      "std x/y", tuple(round(float(v), 2) for v in shifts.std(axis=0)))
