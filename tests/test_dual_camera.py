import io
import queue
import struct
import threading
import time

import cv2
import numpy as np
import pytest

from premonition.dual_camera import DualCamera


def jpeg(value):
    return cv2.imencode(".jpg", np.full((720, 1280, 3), value, np.uint8))[1].tobytes()


def packet(value):
    data = jpeg(value)
    return struct.pack("!I", len(data)) + data


class Stream:
    def __init__(self):
        self.chunks, self.buffer = queue.Queue(), b""

    def push(self, data):
        self.chunks.put(data)

    def read(self, count):
        while not self.buffer:
            chunk = self.chunks.get()
            if chunk is None:
                return b""
            self.buffer = chunk
        value, self.buffer = self.buffer[:count], self.buffer[count:]
        return value


class Process:
    def __init__(self):
        self.stdin, self.stdout = io.BytesIO(), Stream()
        self.stdin.close = lambda: None
        self.stdout.push(b"PVIEW1\n")

    def terminate(self):
        self.stdout.push(None)

    kill = terminate

    def wait(self, timeout=None):
        return 0


def started(processes):
    pending = iter(processes)
    return DualCamera("jetson-usb", popen=lambda argv, **options: next(pending))


def test_start_selects_each_device_without_the_720p_check():
    processes = [Process(), Process()]
    cams = started(processes)
    for p in processes:
        p.stdout.push(packet(90))
    cams.start(warmup_s=0)
    assert b"cv2.VideoCapture(0," in processes[0].stdin.getvalue()
    assert b"cv2.VideoCapture(1," in processes[1].stdin.getvalue()
    assert b"(720, 1280)" not in processes[1].stdin.getvalue()
    cams.close()


def test_snapshot_returns_both_views_upscaled():
    processes = [Process(), Process()]
    cams = started(processes)
    for p in processes:
        p.stdout.push(packet(90))
    cams.start(warmup_s=0)
    frames = cams.snapshot()
    assert set(frames) == {"c922", "usb"}
    assert all(f.image.shape == (1080, 1920, 3) and f.jpeg[:2] == b"\xff\xd8" for f in frames.values())
    cams.close()


def test_snapshot_after_ignores_older_frames():
    processes = [Process(), Process()]
    cams = started(processes)
    for p in processes:
        p.stdout.push(packet(40))
    cams.start(warmup_s=0)
    after = time.perf_counter()
    threading.Timer(0.2, lambda: [p.stdout.push(packet(200)) for p in processes]).start()
    frames = cams.snapshot(after=after, timeout=3)
    assert all(f.t > after and abs(int(f.image.mean()) - 200) < 5 for f in frames.values())
    cams.close()


def test_snapshot_times_out_when_one_view_stalls():
    processes = [Process(), Process()]
    cams = started(processes)
    for p in processes:
        p.stdout.push(packet(90))
    cams.start(warmup_s=0)
    after = time.perf_counter()
    processes[0].stdout.push(packet(120))
    with pytest.raises(TimeoutError):
        cams.snapshot(after=after, timeout=0.3)
    cams.close()


def test_serve_streams_the_frames_the_controller_already_receives():
    import httpx

    processes = [Process(), Process()]
    cams = started(processes)
    for p in processes:
        p.stdout.push(packet(90))
    cams.start(warmup_s=0)
    port = cams.serve(port=0)
    try:
        assert b"/stream/usb" in httpx.get(f"http://127.0.0.1:{port}/").content
        with httpx.stream("GET", f"http://127.0.0.1:{port}/stream/usb", timeout=5) as response:
            assert response.headers["content-type"].startswith("multipart/x-mixed-replace")
            data = b""
            for chunk in response.iter_bytes():
                data += chunk
                if b"\xff\xd9" in data:
                    break
        assert b"\xff\xd8" in data
        assert httpx.get(f"http://127.0.0.1:{port}/stream/other").status_code == 404
    finally:
        cams.close()


def test_status_reports_each_feeds_frame_count_and_age_without_touching_the_streams():
    import httpx

    processes = [Process(), Process()]
    cams = started(processes)
    for p in processes:
        p.stdout.push(packet(90))
    cams.start(warmup_s=0)
    port = cams.serve(port=0)
    try:
        response = httpx.get(f"http://127.0.0.1:{port}/status")
        assert response.headers["access-control-allow-origin"] == "*"
        status = response.json()
        assert {name: feed["count"] for name, feed in status.items()} == {"c922": 1, "usb": 1}
        assert all(0 <= feed["age"] < 5 for feed in status.values())
        cams.feeds["usb"].t -= 10
        cams.feeds["c922"].count = 0
        status = httpx.get(f"http://127.0.0.1:{port}/status").json()
        assert status["usb"]["age"] > 4 and status["c922"]["age"] is None
    finally:
        cams.close()
