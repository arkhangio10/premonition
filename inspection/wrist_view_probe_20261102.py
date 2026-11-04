"""One explicitly requested visibility probe, inside previously observed pulse ranges."""
import argparse
import json
import queue
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from premonition.first_motion import SERVICE
from premonition.jetson import inspect_system, read_commanded_pulses, ssh_argv
from premonition.scene_vision import load_capture
from premonition.teaching_hold import require_no_motion_hold

ROOT = Path(__file__).resolve().parent.parent / "runs"
EXPECTED_HASH = "1a60fbf2a3077113ae0d7e9e6c2e7fc546177421f16ae02abbf6439652337a18"
HOME = dict(base=1499, shoulder=1450, elbow=1499, wrist_pitch=1602, wrist_roll=1499, gripper=1499)


def build_command(reading, joint, target):
    if reading["mode1"] != 33 or reading["prescale"] != 121:
        raise ValueError("Controller is not in the reviewed active 50 Hz state.")
    pulses = reading["commanded_us"]
    if set(pulses) != set(HOME) or any(type(v) is not int for v in pulses.values()):
        raise ValueError("All six outputs must already be active.")
    if any(pulses[j] != HOME[j] for j in ("base", "shoulder", "elbow", "wrist_pitch")):
        raise ValueError("The supporting joints changed from the observation pose.")
    if joint == "wrist_roll":
        if pulses["gripper"] != 1499 or (pulses[joint], target) not in {(1499,1579),(1577,1657),(1577,1499),(1655,1499)}:
            raise ValueError("Roll command is outside the previously observed probe and return.")
    elif joint == "gripper":
        if pulses["wrist_roll"] not in (1499,1577,1655) or (pulses[joint],target) not in {(1499,1618),(1616,1499)}:
            raise ValueError("Gripper command is outside the previously observed opening and return.")
    else:
        raise ValueError("This probe only permits wrist roll or the gripper.")
    return {"id":1,"cmd":"move","targets":dict(pulses,**{joint:target}),"duration":3.0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--joint", choices=("wrist_roll","gripper"), required=True)
    parser.add_argument("--target", type=int, required=True)
    args = parser.parse_args()
    require_no_motion_hold(ROOT)
    inventory = inspect_system("jetson-usb")
    if inventory["arm_processes"] or inventory["programs"]["mindarm_arm.py"]["sha256"] != EXPECTED_HASH:
        raise ValueError("Another arm process exists or the reviewed controller changed.")
    reading = read_commanded_pulses("jetson-usb")
    command = build_command(reading, args.joint, args.target)
    with httpx.Client(base_url="http://127.0.0.1:8765",timeout=10) as client:
        status = client.get("/api/calibration").json()
        preview = client.get("/api/camera/live/status").json()
    if not status["stop_procedure_confirmed"] or not preview.get("active"):
        raise ValueError("Physical stop and live observation must be available.")
    capture = status["capture"]
    load_capture(ROOT, capture)
    if capture.get("restored") or time.time()-(ROOT/"real/captures"/capture["file"]).stat().st_mtime > 120:
        raise ValueError("Take a fresh before-photo, then resume live preview.")
    report = {"id":uuid.uuid4().hex,"created_at":datetime.now(timezone.utc).isoformat(),
              "purpose":"Improve visibility of the gripper, as requested by the operator.",
              "before_readback":reading,"before_capture":capture,"command":command,
              "source_service_sha256":EXPECTED_HASH,"status":"prepared","command_sent":False}
    folder = ROOT/"real/calibration/trials"
    folder.mkdir(parents=True,exist_ok=True)
    path = folder/(report["id"]+".json")
    def save():
        path.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    save()
    process = subprocess.Popen(ssh_argv("jetson-usb","python3 "+SERVICE),
                               stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    replies = queue.Queue()
    def reader():
        for line in process.stdout:
            replies.put(line)
    threading.Thread(target=reader,daemon=True).start()
    try:
        ready = json.loads(replies.get(timeout=15))
        if not ready["ok"] or ready["id"] != 0 or ready["positions"] != reading["commanded_us"]:
            raise ValueError("Controller readiness differs from the fresh readback.")
        report["controller_ready"] = ready
        report["command_sent"],report["status"] = True,"sent_once"
        save()
        process.stdin.write((json.dumps(command)+"\n").encode())
        process.stdin.flush()
        reply = json.loads(replies.get(timeout=10))
        report["controller_reply"] = reply
        if reply["id"] != 1 or not reply["ok"] or reply["stopped"] or reply["positions"] != command["targets"]:
            raise ValueError("Probe did not complete; do not retry automatically.")
        report["status"] = "command_complete_visual_check_pending"
    except BaseException as failure:
        report["status"],report["failure"] = "uncertain_do_not_retry",str(failure)
        try:
            process.stdin.write(b"\n");process.stdin.flush()
        except OSError:
            pass
        raise
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate();process.wait(timeout=5)
        save()
    after = read_commanded_pulses("jetson-usb")
    report["after_readback"] = after
    save()
    if after["mode1"] != 33 or after["prescale"] != 121:
        raise ValueError("Controller setup changed after the probe.")
    if any(after["commanded_us"][j] != reading["commanded_us"][j] for j in HOME if j != args.joint):
        raise ValueError("An unrelated joint's register changed.")
    if after["commanded_us"][args.joint] is None or abs(after["commanded_us"][args.joint]-args.target)>3:
        raise ValueError("Target readback did not match within PWM quantization.")
    print(json.dumps({"trial_id":report["id"],"command":command,"after_readback":after,"status":report["status"]},indent=2))


if __name__ == "__main__":
    main()
