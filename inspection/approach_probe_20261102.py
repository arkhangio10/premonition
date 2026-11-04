"""Single, reviewed direction probe. No trajectory or pickup is enabled."""
import argparse
import json
import queue
import re
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
EXPECTED_HASH = "2ab17e54cf8832712f3f1620815964ddeb45172cd68bc55e84e31a8c8a5d0040"
EXPECTED = dict(base=1499, shoulder=1450, elbow=1499, wrist_pitch=1602,
                wrist_roll=1499, gripper=1616)
ENVELOPE = {"base":(1000,2000),"shoulder":(1000,2000),"elbow":(1000,2300),
            "wrist_pitch":(1180,1980),"wrist_roll":(1000,2000),"gripper":(1130,1950)}


def build_command(reading):
    if reading != {"mode1": 33, "prescale": 121, "commanded_us": EXPECTED}:
        raise ValueError("The probe requires the exact stable open-gripper observation pose.")
    if any(type(v) is not int for v in reading["commanded_us"].values()):
        raise ValueError("All outputs must be active integer pulses.")
    return {"id": 1, "cmd": "move", "targets": dict(EXPECTED, shoulder=1430), "duration": 3.0}


def build_repeat_command(reading, phase):
    if phase not in ("repeat_return", "repeat_probe", "wider_probe"):
        raise ValueError("Unknown repeat phase.")
    start, target = {"repeat_return":(1431,1450), "repeat_probe":(1450,1430),
                     "wider_probe":(1431,1370)}[phase]
    expected = dict(EXPECTED, shoulder=start)
    if reading != {"mode1":33, "prescale":121, "commanded_us":expected}:
        raise ValueError("The repeat requires the exact last observed controller reading.")
    if any(type(v) is not int for v in reading["commanded_us"].values()):
        raise ValueError("All outputs must be active integer pulses.")
    return {"id":1,"cmd":"move","targets":dict(expected,shoulder=target),
            "duration":4.0 if phase=="wider_probe" else 3.0}


def build_base_command(reading):
    expected=dict(EXPECTED,shoulder=1372)
    if reading != {"mode1":33,"prescale":121,"commanded_us":expected}:
        raise ValueError("The base probe requires the exact observed shoulder checkpoint.")
    if any(type(v) is not int for v in reading["commanded_us"].values()):
        raise ValueError("All outputs must be active integer pulses.")
    return {"id":1,"cmd":"move","targets":dict(expected,base=1559),"duration":4.0}


def validate_readback(before,after,command):
    changed=[j for j in EXPECTED if command["targets"][j]!=before["commanded_us"][j]]
    if len(changed)!=1:
        raise ValueError("Exactly one joint must change.")
    joint=changed[0]
    if after["mode1"]!=33 or after["prescale"]!=121:
        raise ValueError("The controller setup changed.")
    if set(after["commanded_us"])!=set(EXPECTED):
        raise ValueError("The readback must include all six channels.")
    if any(after["commanded_us"][j]!=before["commanded_us"][j] for j in EXPECTED if j!=joint):
        raise ValueError("An unrelated channel changed.")
    actual=after["commanded_us"][joint]
    if type(actual) is not int or abs(actual-command["targets"][joint])>3:
        raise ValueError("The changed channel differs from its target.")


def build_review_command(reading,review):
    """One manually reviewed step, capped locally; never derives motion from an image/model."""
    if reading.get("mode1")!=33 or reading.get("prescale")!=121:
        raise ValueError("The active reviewed controller setup is required.")
    before=reading.get("commanded_us",{})
    if set(before)!=set(EXPECTED) or any(type(v) is not int for v in before.values()):
        raise ValueError("All six channels must already be active integer pulses.")
    if reading!=review.get("expected_readback"):
        raise ValueError("The controller changed since this step was reviewed.")
    if review.get("table_prepared_operator_confirmed") is not True:
        raise ValueError("The table preparation must be confirmed.")
    command=review.get("command",{})
    if set(command)!={"id","cmd","targets","duration"} or command["id"]!=1 or command["cmd"]!="move":
        raise ValueError("Only one move command is accepted.")
    if type(command["duration"]) not in (int,float) or command["duration"]!=4:
        raise ValueError("Teaching steps must last four seconds.")
    targets=command["targets"]
    if not isinstance(targets,dict) or set(targets)!=set(EXPECTED):
        raise ValueError("All six targets are required.")
    for joint,value in targets.items():
        low,high=ENVELOPE[joint]
        if type(value) is not int or not low<value<high or not low<before[joint]<high:
            raise ValueError("Targets must stay inside the historical envelope, away from its endpoints.")
    changed=[j for j in EXPECTED if targets[j]!=before[j]]
    if len(changed)!=1:
        raise ValueError("A teaching step changes exactly one joint.")
    joint=changed[0]
    if abs(targets[joint]-before[joint])>(80 if joint=="gripper" else 60):
        raise ValueError("The teaching step exceeds its single-joint pulse cap.")
    return {**command,"targets":dict(targets)}


def validate_capture_review(review,capture):
    if (review.get("reviewed_capture_file")!=capture.get("file")
            or review.get("reviewed_capture_sha256")!=capture.get("sha256")
            or not re.fullmatch(r"[0-9a-f]{64}",review.get("reviewed_capture_sha256", ""))):
        raise ValueError("Visually review this exact before-photo and bind its file/hash before actuation.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument("--phase",choices=("initial","repeat_return","repeat_probe","wider_probe","base_probe"))
    mode.add_argument("--review")
    args=parser.parse_args()
    require_no_motion_hold(ROOT)
    phase=args.phase or "initial"
    suffix = "" if phase == "initial" else "_"+phase
    if args.review and not re.fullmatch(r"teaching_step_[a-z0-9_]+\.json",args.review):
        raise ValueError("Use a teaching-step review filename within the calibration folder.")
    review_path = ROOT / "real/calibration" / (args.review or "approach_probe_review"+suffix+"_20261102.json")
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if review.get("base_fixed_operator_confirmed") is not True or review.get("status") != "prepared":
        raise ValueError("The physical base confirmation and an unused review are required.")
    inventory = inspect_system("jetson-usb")
    if inventory["arm_processes"] or inventory["programs"]["mindarm_arm.py"]["sha256"] != EXPECTED_HASH:
        raise ValueError("Another arm process exists or the reviewed source changed.")
    before = read_commanded_pulses("jetson-usb")
    command = (build_review_command(before,review) if args.review else build_command(before)
               if phase=="initial" else build_base_command(before) if phase=="base_probe"
               else build_repeat_command(before,phase))
    if command != review["command"]:
        raise ValueError("The command differs from the reviewed probe.")
    with httpx.Client(base_url="http://127.0.0.1:8765", timeout=10) as client:
        status = client.get("/api/calibration").raise_for_status().json()
        preview = client.get("/api/camera/live/status").raise_for_status().json()
    capture = status["capture"]
    load_capture(ROOT, capture)
    if args.review:
        validate_capture_review(review,capture)
    if not status["stop_procedure_confirmed"] or not preview.get("active"):
        raise ValueError("The physical stop and live camera must be available.")
    if capture.get("restored") or time.time()-(ROOT/"real/captures"/capture["file"]).stat().st_mtime > 120:
        raise ValueError("A fresh before-photo is required.")
    trial = {"id": uuid.uuid4().hex, "created_at": datetime.now(timezone.utc).isoformat(),
             "purpose": "Single-joint direction probe before teaching a new pickup route.",
             "review_file": review_path.name, "review":review, "before_readback": before, "before_capture": capture,
             "command": command, "command_sent": False, "status": "prepared",
             "source_service_sha256": EXPECTED_HASH}
    folder = ROOT / "real/calibration/trials"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (trial["id"]+".json")
    def save():
        path.write_text(json.dumps(trial, indent=2)+"\n", encoding="utf-8")
    save()
    # Mark consumed before starting a controller. A failed/uncertain attempt is never retried.
    review.update(status="consumed_do_not_retry", trial_id=trial["id"])
    review_path.write_text(json.dumps(review, indent=2)+"\n", encoding="utf-8")
    process = subprocess.Popen(ssh_argv("jetson-usb", "python3 "+SERVICE),
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    replies = queue.Queue()
    def reader():
        for line in process.stdout:
            replies.put(line)
    threading.Thread(target=reader, daemon=True).start()
    try:
        ready = json.loads(replies.get(timeout=15))
        if ready.get("id") != 0 or ready.get("ok") is not True or ready.get("positions") != before["commanded_us"]:
            raise ValueError("Controller readiness changed from the preflight reading.")
        trial["controller_ready"] = ready
        trial.update(command_sent=True, status="sent_once")
        save()
        process.stdin.write((json.dumps(command)+"\n").encode())
        process.stdin.flush()
        reply = json.loads(replies.get(timeout=10))
        trial["controller_reply"] = reply
        if reply.get("id") != 1 or reply.get("ok") is not True or reply.get("stopped") or reply.get("positions") != command["targets"]:
            raise ValueError("The probe did not complete. Do not resend it.")
        trial["status"] = "command_complete_visual_check_pending"
    except BaseException as failure:
        trial.update(status="uncertain_do_not_retry", failure=str(failure))
        try:
            process.stdin.write(b"\n"); process.stdin.flush()
        except OSError:
            pass
        raise
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate(); process.wait(timeout=5)
        save()
    after = read_commanded_pulses("jetson-usb")
    trial["after_readback"] = after
    save()
    validate_readback(before,after,command)
    print(json.dumps({"trial_id": trial["id"], "after_readback": after, "status": trial["status"]}, indent=2))


if __name__ == "__main__":
    main()
