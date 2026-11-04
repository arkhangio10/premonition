"""One supervised closed-loop iteration. `decide` only proposes; `execute` sends one reviewed step."""
import argparse
import copy
import dataclasses
import json
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import httpx

from inspection.approach_probe_20261102 import build_review_command
from premonition.jetson import read_commanded_pulses
from premonition.teaching_hold import require_no_motion_hold
from premonition.visual_servo import LoopState, decide, locate_tip

ROOT = Path(__file__).resolve().parent.parent / "runs"
BASE = "http://127.0.0.1:8765"
MAX_PHOTO_AGE_S = 105


def record_path(run):
    return ROOT / "real/calibration" / f"visual_loop_{run}.json"


def load_record(run, target):
    path = record_path(run)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if target is None:
        raise ValueError("A new run needs --target X Y.")
    return {"run": run, "state": dataclasses.asdict(LoopState(target=tuple(target))), "history": []}


def save_record(record):
    path = record_path(record["run"])
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def take_photo(client):
    live = client.get("/api/camera/live/status").json()
    if live.get("running"):
        client.post("/api/camera/live/stop", json={"token": live["token"]}).raise_for_status()
    client.post("/api/calibration/inspect").raise_for_status()
    return client.post("/api/camera/capture").raise_for_status().json()


def run_decide(args, client):
    record = load_record(args.run, args.target)
    proposal = record.get("proposal")
    if proposal and not proposal["executed"]:
        record["state"] = proposal["state_before"]
    capture = take_photo(client)
    image = cv2.imread(str(ROOT / "real/captures" / capture["file"]))
    tip = locate_tip(image)
    pulses = read_commanded_pulses("jetson-usb")["commanded_us"]
    before = copy.deepcopy(record["state"])
    state = LoopState(**record["state"])
    decision = decide(state, tip, pulses)
    record["state"] = dataclasses.asdict(state)
    entry = {"at": datetime.now(timezone.utc).isoformat(), "capture": capture["file"], "tip": tip,
             "pulses": pulses, "decision": dataclasses.asdict(decision)}
    record["history"].append(entry)
    record["proposal"] = None
    if decision.kind == "move":
        record["proposal"] = {"joint": decision.joint, "target_us": pulses[decision.joint] + decision.delta,
                              "capture": capture, "state_before": before, "executed": False}
    save_record(record)
    print(json.dumps({"entry": entry, "sha256": capture["sha256"], "moves": state.moves, "retries": state.retries,
                      "sensitivity": state.sensitivity}, indent=1))


def hold_preview(token):
    try:
        with httpx.stream("GET", f"{BASE}/api/camera/live.mjpg?token={token}", timeout=None) as stream:
            for _ in stream.iter_bytes():
                pass
    except httpx.HTTPError:
        pass


def run_execute(args, client):
    record = load_record(args.run, None)
    proposal = record.get("proposal")
    if not proposal or proposal["executed"]:
        raise ValueError("Decide a new step first.")
    capture = proposal["capture"]
    current = client.get("/api/calibration").raise_for_status().json()["capture"]
    if args.reviewed_capture_sha256 != capture["sha256"] or capture["sha256"] != current["sha256"]:
        raise ValueError("The reviewed image differs from the current capture.")
    before = read_commanded_pulses("jetson-usb")
    name = f"teaching_step_visual_{args.run}_{len(record['history']):02d}.json"
    review = {"status": "prepared", "prepared_at": datetime.now(timezone.utc).isoformat(),
              "base_fixed_operator_confirmed": True, "table_prepared_operator_confirmed": True,
              "authorization": "Operator requested closed-loop visual approach with retries; each photo reviewed before its step.",
              "expected_readback": before, "purpose": f"Visual loop {args.run}: {proposal['joint']} to {proposal['target_us']}.",
              "reviewed_capture_file": capture["file"], "reviewed_capture_sha256": capture["sha256"],
              "command": {"id": 1, "cmd": "move", "duration": 4.0,
                          "targets": dict(before["commanded_us"], **{proposal["joint"]: proposal["target_us"]})}}
    build_review_command(before, review)
    path = ROOT / "real/calibration" / name
    if path.exists():
        raise ValueError("Never reset an existing one-use review.")
    path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    token = uuid.uuid4().hex
    threading.Thread(target=hold_preview, args=(token,), daemon=True).start()
    deadline = time.time() + 16
    while time.time() < deadline:
        live = client.get("/api/camera/live/status").json()
        if live.get("token") == token and live.get("active"):
            break
        time.sleep(.3)
    else:
        raise ValueError("The live preview did not start; nothing moved.")
    if time.time() - (ROOT / "real/captures" / capture["file"]).stat().st_mtime > MAX_PHOTO_AGE_S:
        raise ValueError("The reviewed photo is too old; nothing moved.")
    proposal["executed"] = True
    save_record(record)
    result = subprocess.run([sys.executable, "-m", "inspection.approach_probe_20261102", "--review", name],
                            capture_output=True, text=True, timeout=60)
    client.post("/api/camera/live/stop", json={"token": token})
    print(result.stdout[-500:] or result.stderr[-500:])
    if result.returncode:
        raise ValueError("The step did not complete. Do not resend it.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("decide", "execute"))
    parser.add_argument("--run", required=True)
    parser.add_argument("--target", type=float, nargs=2)
    parser.add_argument("--reviewed-capture-sha256")
    args = parser.parse_args()
    require_no_motion_hold(ROOT)
    with httpx.Client(base_url=BASE, timeout=60) as client:
        (run_decide if args.command == "decide" else run_execute)(args, client)


if __name__ == "__main__":
    main()
