"""Compare C922 lens focus on the stationary gripper; never access the arm."""
import base64
import json
import subprocess
from pathlib import Path

from premonition.jetson import ssh_argv


REMOTE = r'''
import base64
import json
import subprocess
import time
import cv2

def control(value):
    subprocess.check_call(['v4l2-ctl', '-d', '/dev/video0', '--set-ctrl=' + value], stdout=subprocess.DEVNULL)

cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
cap.set(cv2.CAP_PROP_FPS, 30)
results = []
complete = False
try:
    control('focus_auto=0')
    for focus in (0, 10, 15, 20, 25, 30, 40):
        control('focus_absolute=' + str(focus))
        began = time.monotonic()
        image = None
        while time.monotonic() - began < 1.2:
            ok, frame = cap.read()
            if ok:
                image = frame
        if image is None or image.shape[:2] != (1080, 1920):
            raise RuntimeError('No 1920x1080 image at focus ' + str(focus))
        # Same stationary gripper region across frames; not a calibrated quality threshold.
        gray = cv2.cvtColor(image[30:260, 470:930], cv2.COLOR_BGR2GRAY)
        encoded_ok, jpeg = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not encoded_ok:
            raise RuntimeError('JPEG encoding failed')
        results.append({'focus': focus,
                        'gripper_roi_sharpness': float(cv2.Laplacian(gray, cv2.CV_64F).var()),
                        'jpeg_b64': base64.b64encode(jpeg.tobytes()).decode('ascii')})
    best = max(results, key=lambda item: item['gripper_roi_sharpness'])
    control('focus_absolute=' + str(best['focus']))
    complete = True
finally:
    cap.release()
    if not complete:
        control('focus_auto=1')
print(json.dumps({'selected_focus': best['focus'], 'roi_xywh': [470, 30, 460, 230], 'frames': results}))
'''


def main():
    result = subprocess.run(ssh_argv('jetson-usb', 'python3 -'), input=REMOTE.encode(),
                            capture_output=True, timeout=50)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', 'replace')[-800:])
    reply = json.loads(result.stdout.decode().strip().splitlines()[-1])
    folder = Path(__file__).resolve().parent / 'c922-focus'
    folder.mkdir(exist_ok=True)
    for frame in reply['frames']:
        path = folder / ('focus-%03d.jpg' % frame['focus'])
        path.write_bytes(base64.b64decode(frame.pop('jpeg_b64')))
        frame['file'] = path.name
    (folder / 'result.json').write_text(json.dumps(reply, indent=2), encoding='utf-8')
    print(json.dumps(reply, indent=2))


if __name__ == '__main__':
    main()
