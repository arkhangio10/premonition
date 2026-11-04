#!/usr/bin/env python3
"""Camera-only preview over stdout. Compatible with Jetson Python 3.6."""
import signal
import struct
import sys
import time

import cv2


def main():
    running = [True]
    def stop(*_):
        running[0] = False
    signal.signal(signal.SIGHUP, stop)
    signal.signal(signal.SIGTERM, stop)
    camera = cv2.VideoCapture(0, cv2.CAP_V4L2)
    try:
        if not camera.isOpened():
            raise RuntimeError("Camera unavailable")
        camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        camera.set(cv2.CAP_PROP_FPS, 10)
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        output = sys.stdout.buffer
        output.write(b"PVIEW1\n")
        output.flush()
        while running[0]:
            began = time.monotonic()
            ok, frame = camera.read()
            if not ok:
                raise RuntimeError("Camera stopped returning frames")
            if frame.shape[:2] != (720, 1280):
                raise RuntimeError("Preview requires 1280x720")
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ok:
                raise RuntimeError("JPEG encoding failed")
            jpeg = encoded.tobytes()
            output.write(struct.pack("!I", len(jpeg)))
            output.write(jpeg)
            output.flush()
            time.sleep(max(0, .125 - (time.monotonic() - began)))
    except BrokenPipeError:
        pass
    finally:
        camera.release()


if __name__ == "__main__":
    main()
