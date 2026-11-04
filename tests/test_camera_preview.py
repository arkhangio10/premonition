import io
import struct
import threading

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from premonition.camera_preview import CameraPreview, read_exact
from premonition.jetson import CameraError


def jpeg():
    return cv2.imencode(".jpg", np.full((720, 1280, 3), 100, np.uint8))[1].tobytes()


class Input(io.BytesIO):
    def close(self):
        self.sent = self.getvalue()
        super().close()


class Reader:
    def __init__(self, data, stopped):
        self.data, self.stopped = io.BytesIO(data), stopped

    def read(self, count):
        value = self.data.read(min(count, 127))
        if value:
            return value
        assert self.stopped.wait(3), "Preview did not terminate its process"
        return b""


class Process:
    def __init__(self, data):
        self.stopped = threading.Event()
        self.stdin = Input()
        self.stdout = Reader(data, self.stopped)
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0
        self.stopped.set()

    kill = terminate

    def wait(self, timeout=None):
        self.terminate()
        return 0


def make_preview(data, **kwargs):
    lock, process = threading.Lock(), Process(data)
    calls = []
    def popen(argv, **options):
        calls.append((argv, options))
        return process
    preview = CameraPreview("jetson-usb", "a"*32, lock, popen=popen, **kwargs)
    return preview, lock, process, calls


def test_preview_uses_camera_only_script_and_releases_camera_after_stop():
    frame = jpeg()
    preview, lock, process, calls = make_preview(b"PVIEW1\n" + struct.pack("!I", len(frame)) + frame)
    try:
        sequence, observed = preview.next_frame(0, timeout=2)
        assert sequence == 1 and observed == frame
        assert preview.status()["active"] is True
        assert lock.locked()
        assert calls[0][0][-1] == "python3 -u -"
        assert "StrictHostKeyChecking=yes" in calls[0][0]
        sent = process.stdin.sent
        assert b"VideoCapture" in sent and b"\r\n" not in sent
        assert all(term not in sent for term in (b"smbus", b"mindarm", b"servo_test"))
    finally:
        preview.stop()
    assert not lock.locked() and preview.done.is_set()
    assert preview.status()["active"] is False


@pytest.mark.parametrize("data", [b"WRONG!!", b"PVIEW1\n"+struct.pack("!I", 2_000_001),
                                  b"PVIEW1\n"+struct.pack("!I", 4)+b"bad!"])
def test_invalid_stream_data_stops_process_and_frees_camera(data):
    preview, lock, process, _ = make_preview(data)
    assert preview.done.wait(2)
    assert preview.status()["error"]
    assert process.stopped.is_set() and not lock.locked()


def test_no_frames_triggers_watchdog_and_frees_camera():
    preview, lock, _, _ = make_preview(b"", startup_timeout=.02)
    assert preview.done.wait(2)
    assert "timed out" in preview.status()["error"] and not lock.locked()


def test_busy_camera_does_not_start_a_second_process():
    lock = threading.Lock()
    lock.acquire()
    def forbidden(*args, **kwargs):
        pytest.fail("Camera is already reserved")
    with pytest.raises(CameraError, match="already in use"):
        CameraPreview("jetson-usb", "a"*32, lock, popen=forbidden)
    lock.release()


def test_failed_process_start_releases_camera():
    lock = threading.Lock()
    def fail(*args, **kwargs):
        raise OSError("unavailable")
    with pytest.raises(OSError):
        CameraPreview("jetson-usb", "a"*32, lock, popen=fail)
    assert not lock.locked()


def test_short_transport_read_is_not_accepted_as_a_frame():
    with pytest.raises(CameraError, match="ended"):
        read_exact(io.BytesIO(b"12"), 4)


def test_web_preview_has_no_meta_calls_and_closes_on_stream_completion(tmp_path, monkeypatch):
    from premonition import web
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    sessions = []
    image = jpeg()
    class FakePreview:
        def __init__(self, host, token, camera_lock):
            self.token, self.done, self.count, self.stops = token, threading.Event(), 0, 0
            sessions.append(self)
        def next_frame(self, after):
            if after < 2:
                return after+1, image
            self.done.set()
            return None
        def request_stop(self):
            self.stops += 1
            self.done.set()
        def stop(self):
            self.request_stop()
        def status(self):
            return {"token": self.token, "running": not self.done.is_set(), "active": False}
    monkeypatch.setattr(web, "CameraPreview", FakePreview)
    app = TestClient(web.create_app(tmp_path), base_url="http://127.0.0.1")
    assert app.get("/api/camera/live/status").json()["active"] is False
    assert sessions == []
    assert app.get("/api/camera/live.mjpg?token=bad").status_code == 422
    assert sessions == []
    response = app.get("/api/camera/live.mjpg?token="+"a"*32)
    assert response.status_code == 200
    assert "multipart/x-mixed-replace" in response.headers["content-type"]
    assert response.content.count(b"--frame") == 2
    assert response.content.count(image) == 2
    assert sessions[0].stops == 1
    assert app.post("/api/camera/live/stop", json={"token": "b"*32}).status_code == 409
    assert sessions[0].stops == 1
