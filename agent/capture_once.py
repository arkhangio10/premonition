#!/usr/bin/env python3
"""Captura un fotograma y lo imprime como JSON. Solo usa la cámara: no toca el control motriz."""
import argparse
import base64
import json
import sys
import time

import cv2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token", required=True)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--reads", type=int, default=8)
    args = parser.parse_args()
    began = time.monotonic()
    capture = cv2.VideoCapture(args.device, cv2.CAP_V4L2)
    capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    image = None
    good_reads = 0
    for _ in range(args.reads):  # Descarta lo acumulado en el búfer para no devolver un fotograma viejo.
        ok, candidate = capture.read()
        if ok:
            image, good_reads = candidate, good_reads + 1
    capture.release()
    if image is None:
        print(json.dumps({"ok": False, "token": args.token, "error": "camera returned no frame"}))
        sys.exit(1)
    encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])[1]
    print(json.dumps({"ok": True, "token": args.token, "width": image.shape[1], "height": image.shape[0],
                      "good_reads": good_reads, "reads": args.reads, "elapsed_s": time.monotonic() - began,
                      "jpeg_b64": base64.b64encode(encoded.tobytes()).decode("ascii")}))


if __name__ == "__main__":
    main()
