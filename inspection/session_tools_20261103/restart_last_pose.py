"""Energize the released outputs at the last commanded pose, one channel every 0.5 s. Operator chose this on 2026-11-02."""
import json, queue, subprocess, sys, threading
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, ".")
from premonition.jetson import inspect_system, read_commanded_pulses, ssh_argv
from premonition.teaching_hold import require_no_motion_hold

ROOT = Path("runs")
OUT = ROOT / "real/calibration/restart_last_pose_result_20261102.json"
EXPECTED = "1a60fbf2a3077113ae0d7e9e6c2e7fc546177421f16ae02abbf6439652337a18"
TARGETS = dict(base=1567, shoulder=1367, elbow=1646, wrist_pitch=1562, wrist_roll=1558, gripper=1538)
COMMAND = {"id": 1, "cmd": "start", "targets": TARGETS, "duration": 2.0, "stagger": .5}

def save(report):
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

require_no_motion_hold(ROOT)
assert not OUT.exists(), "Already attempted; do not retry blindly"
inventory = inspect_system("jetson-usb")
assert inventory["programs"]["mindarm_arm.py"]["sha256"] == EXPECTED, "Controller source changed"
assert not inventory["arm_processes"], "Another arm process is running"
before = read_commanded_pulses("jetson-usb")
assert before["mode1"] == 17 and before["prescale"] == 30, "Controller setup changed"
assert all(v is None for v in before["commanded_us"].values()), "Outputs changed"
report = {"created_at": datetime.now(timezone.utc).isoformat(),
          "authorization": "Operator chose 'Última postura' after being told the controller reset (MODE1=17, outputs off) and C922 moved; requires servo supply on and hands clear.",
          "reason": "Controller found reset; arm visibly near last commanded pose in both cameras (photos now01_*). Released channels energize directly at target.",
          "before_readback": before, "source_service_sha256": EXPECTED, "command": COMMAND,
          "command_sent": False, "status": "starting_controller"}
save(report)
process = subprocess.Popen(ssh_argv("jetson-usb", "python3 /home/abelbrayan/mindarm_arm.py"),
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
replies = queue.Queue()
threading.Thread(target=lambda: [replies.put(line) for line in process.stdout], daemon=True).start()
try:
    ready = json.loads(replies.get(timeout=15))
    assert ready["ok"] and ready["id"] == 0 and ready["positions"] == before["commanded_us"], "Startup differs from preflight"
    report.update(controller_ready=ready, command_sent=True, status="command_sent_once")
    save(report)
    process.stdin.write((json.dumps(COMMAND) + "\n").encode())
    process.stdin.flush()
    reply = json.loads(replies.get(timeout=12))
    report["controller_reply"] = reply
    assert reply["id"] == 1 and reply["ok"] and not reply["stopped"] and reply["positions"] == TARGETS, "Start not acknowledged"
    report["status"] = "controller_complete_physical_observation_pending"
except BaseException as failure:
    report.update(status="uncertain_do_not_retry", failure=str(failure))
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
    save(report)
after = read_commanded_pulses("jetson-usb")
report["after_readback"] = after
save(report)
print(json.dumps({"status": report["status"], "after": after}))
assert after["prescale"] == 121 and not after["mode1"] & 16
assert all(abs(after["commanded_us"][j] - TARGETS[j]) <= 3 for j in TARGETS)
