"""Bounded, camera-only SSH preview. Its frames are never verification evidence."""
import struct
import subprocess
import threading
import time

from .jetson import CameraError, _script, ssh_argv
from .perception import decode_image


def read_exact(stream, count):
    data = bytearray()
    while len(data) < count:
        chunk = stream.read(count-len(data))
        if not chunk:
            raise CameraError("Preview connection ended.")
        data.extend(chunk)
    return bytes(data)


class CameraPreview:
    def __init__(self, host, token, camera_lock, popen=None, startup_timeout=12, stale_timeout=5):
        script = _script("preview_camera.py")
        if not camera_lock.acquire(blocking=False):
            raise CameraError("The camera is already in use.")
        self.token, self.camera_lock = token, camera_lock
        self.done, self.stopping = threading.Event(), threading.Event()
        self.condition = threading.Condition()
        self.sequence, self.jpeg, self.error = 0, None, None
        self.started = time.monotonic()
        self.first_frame, self.updated = None, None
        try:
            self.process = (popen or subprocess.Popen)(
                ssh_argv(host, "python3 -u -"), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0)
            self.process.stdin.write(script)
            self.process.stdin.close()
        except BaseException:
            if hasattr(self, "process") and self.process.poll() is None:
                self.process.terminate()
            camera_lock.release()
            raise
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.watcher = threading.Thread(target=self._watch, args=(startup_timeout, stale_timeout), daemon=True)
        self.watcher.start()

    def _read(self):
        try:
            if read_exact(self.process.stdout, 7) != b"PVIEW1\n":
                raise CameraError("Invalid camera preview header.")
            while not self.stopping.is_set():
                length = struct.unpack("!I", read_exact(self.process.stdout, 4))[0]
                if not 4 <= length <= 2_000_000:
                    raise CameraError("Invalid preview frame size.")
                jpeg = read_exact(self.process.stdout, length)
                if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
                    raise CameraError("Invalid preview JPEG.")
                if not self.sequence:
                    image = decode_image(jpeg)
                    if image is None or image.shape[:2] != (720, 1280):
                        raise CameraError("Unexpected preview dimensions.")
                with self.condition:
                    now = time.monotonic()
                    self.first_frame = self.first_frame or now
                    self.updated, self.jpeg = now, jpeg
                    self.sequence += 1
                    self.condition.notify_all()
        except (CameraError, OSError, ValueError) as failure:
            if not self.stopping.is_set():
                self.error = str(failure)
        finally:
            self.request_stop()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
            finally:
                self.camera_lock.release()
                self.done.set()
                with self.condition:
                    self.condition.notify_all()

    def _watch(self, startup_timeout, stale_timeout):
        while not self.stopping.wait(.1):
            deadline = stale_timeout if self.updated else startup_timeout
            if time.monotonic() - (self.updated or self.started) > deadline:
                self.error = "Camera preview timed out."
                self.request_stop()

    def request_stop(self):
        self.stopping.set()
        if self.process.poll() is None:
            try:
                self.process.terminate()
            except OSError:
                pass

    def stop(self):
        self.request_stop()
        self.reader.join(timeout=4.5)
        if not self.done.is_set():
            raise CameraError("Preview has not released the camera yet.")

    def next_frame(self, after, timeout=1):
        with self.condition:
            self.condition.wait_for(lambda: self.sequence > after or self.done.is_set(), timeout)
            return (self.sequence, self.jpeg) if self.sequence > after else None

    def status(self):
        with self.condition:
            age = time.monotonic()-self.updated if self.updated else None
            elapsed = self.updated-self.first_frame if self.updated and self.first_frame else 0
            running = not self.stopping.is_set() and not self.done.is_set()
            return {"token": self.token, "running": running,
                    "active": running and age is not None and age < 3,
                    "frames": self.sequence, "width": 1280, "height": 720,
                    "fps": round((self.sequence-1)/elapsed, 1) if elapsed else 0,
                    "last_frame_age_s": round(age, 2) if age is not None else None, "error": self.error}
