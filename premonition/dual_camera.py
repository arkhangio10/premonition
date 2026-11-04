"""Both cameras streaming for a whole session; frames are upscaled to the 1920x1080 pixel convention."""
import json
import struct
import subprocess
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

from .camera_preview import read_exact
from .jetson import CameraError, _script, ssh_argv

VIEWS = {"c922": 0, "usb": 1}
SIZE = (1920, 1080)
LIVE_PAGE = b"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Arm live</title>
<style>body{margin:0;background:#111}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:8px;padding:8px}
img{width:100%;display:block}</style></head><body><main>
<img src="/stream/c922" alt="Live front camera"><img src="/stream/usb" alt="Live side camera"></main></body></html>"""


@dataclass(frozen=True)
class Frame:
    t: float
    image: np.ndarray
    jpeg: bytes


class Feed:
    def __init__(self, process, changed: threading.Condition):
        self.process, self.changed = process, changed
        self.t, self.jpeg, self.count, self.error = 0.0, None, 0, None

    def read(self):
        try:
            if read_exact(self.process.stdout, 7) != b"PVIEW1\n":
                raise CameraError("invalid preview header")
            while True:
                length = struct.unpack("!I", read_exact(self.process.stdout, 4))[0]
                jpeg = read_exact(self.process.stdout, length)
                with self.changed:
                    self.t, self.jpeg, self.count = time.perf_counter(), jpeg, self.count + 1
                    self.changed.notify_all()
        except Exception as failure:
            with self.changed:
                self.error = str(failure)
                self.changed.notify_all()


class DualCamera:
    def __init__(self, host: str, popen=subprocess.Popen):
        self.host, self.popen = host, popen
        self.changed, self.feeds, self.server = threading.Condition(), {}, None

    def start(self, warmup_s: float = 5.0):
        launched = time.perf_counter()
        for view, device in VIEWS.items():
            script = (_script("preview_camera.py")
                      .replace(b"cv2.VideoCapture(0,", f"cv2.VideoCapture({device},".encode())
                      .replace(b"if frame.shape[:2] != (720, 1280):", b"if False:"))
            process = self.popen(ssh_argv(self.host, "python3 -u -"), stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            process.stdin.write(script)
            process.stdin.close()
            self.feeds[view] = Feed(process, self.changed)
            threading.Thread(target=self.feeds[view].read, daemon=True).start()
        self.snapshot(after=launched + warmup_s, timeout=warmup_s + 15)

    def snapshot(self, after: float | None = None, timeout: float = 5.0) -> dict[str, Frame]:
        after = -1.0 if after is None else after
        ready = lambda: all(f.jpeg is not None and f.t > after for f in self.feeds.values())
        with self.changed:
            if not self.changed.wait_for(lambda: ready() or any(f.error for f in self.feeds.values()), timeout):
                raise TimeoutError(f"No frame after {after:.2f} from every view within {timeout} s")
            failed = {v: f.error for v, f in self.feeds.items() if f.error}
            if failed:
                raise CameraError(f"Camera stream ended: {failed}")
            latest = {v: (f.t, f.jpeg) for v, f in self.feeds.items()}
        frames = {}
        for view, (t, jpeg) in latest.items():
            image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise CameraError(f"{view} sent an undecodable frame")
            if image.shape[1::-1] != SIZE:
                image = cv2.resize(image, SIZE, interpolation=cv2.INTER_LINEAR)
            frames[view] = Frame(t, image, jpeg)
        return frames

    def serve(self, port: int = 8767) -> int:
        """Live view of the frames the controller already receives; it never opens a camera itself."""
        cams = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == "/":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(LIVE_PAGE)
                    return
                if self.path == "/status":
                    now = time.perf_counter()
                    body = json.dumps({name: {"count": feed.count, "age": now - feed.t if feed.count else None}
                                       for name, feed in cams.feeds.items()}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                view = self.path.removeprefix("/stream/")
                if view not in cams.feeds:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                feed, count = cams.feeds[view], -1
                try:
                    while True:
                        with cams.changed:
                            cams.changed.wait_for(lambda: feed.count != count or feed.error, timeout=5)
                            if feed.error:
                                return
                            jpeg, count = feed.jpeg, feed.count
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jpeg)
                                         + jpeg + b"\r\n")
                except (BrokenPipeError, ConnectionError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self.server.server_address[1]

    def close(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        for feed in self.feeds.values():
            feed.process.terminate()
            try:
                feed.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                feed.process.kill()
        self.feeds = {}
