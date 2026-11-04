"""Run only the HOME restart explicitly prepared and confirmed on 2026-11-02."""
import json
import queue
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from premonition.jetson import capture_to_disk, inspect_system, read_commanded_pulses, ssh_argv
from premonition.teaching_hold import require_no_motion_hold

ROOT = Path(__file__).resolve().parent.parent / "runs"
FOLDER = ROOT / "real/calibration"
EXPECTED = "1a60fbf2a3077113ae0d7e9e6c2e7fc546177421f16ae02abbf6439652337a18"
TARGETS = dict(base=1500, shoulder=1450, elbow=1500, wrist_pitch=1600, wrist_roll=1500, gripper=1500)


def save(report):
    (FOLDER / "restart_home_result_20261102.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")


def main():
    require_no_motion_hold(ROOT)
    inventory = inspect_system("jetson-usb")
    assert inventory["programs"]["mindarm_arm.py"]["sha256"] == EXPECTED, "Controller source changed"
    assert not inventory["arm_processes"], "Another arm process is running"
    before = read_commanded_pulses("jetson-usb")
    assert before["mode1"] == 17 and before["prescale"] == 30, "Controller setup changed"
    assert set(before["commanded_us"]) == set(TARGETS) and all(v is None for v in before["commanded_us"].values()), "Outputs changed"
    review = json.loads((FOLDER / "restart_home_review.json").read_text(encoding="utf-8"))
    assert review["command"]["targets"] == TARGETS
    assert review["command"]["cmd"] == "start" and review["command"]["stagger"] == .5
    review["operator_setup_confirmed_for_restart"] = True
    (FOLDER / "restart_home_review.json").write_text(json.dumps(review, indent=2)+"\n", encoding="utf-8")
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "operator_setup_confirmed": True,
              "physical_stop_operator_report": review["physical_stop_operator_report"],
              "before_readback": before, "source_service_sha256": EXPECTED,
              "command": review["command"], "command_sent": False, "status": "starting_controller"}
    save(report)
    process = subprocess.Popen(ssh_argv("jetson-usb", "python3 /home/abelbrayan/mindarm_arm.py"),
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    replies = queue.Queue()
    def read_lines():
        for line in process.stdout:
            replies.put(line)
    threading.Thread(target=read_lines, daemon=True).start()
    try:
        ready = json.loads(replies.get(timeout=15))
        assert ready["ok"] and ready["id"] == 0 and ready["positions"] == before["commanded_us"], "Startup differs from preflight"
        report["controller_ready"] = ready
        report["command_sent"] = True
        report["status"] = "command_sent_once"
        save(report)
        process.stdin.write((json.dumps(review["command"])+"\n").encode())
        process.stdin.flush()
        reply = json.loads(replies.get(timeout=12))
        report["controller_reply"] = reply
        assert reply["id"] == 1 and reply["ok"] and not reply["stopped"] and reply["positions"] == TARGETS, "HOME not acknowledged"
        report["status"] = "controller_complete_physical_observation_pending"
    except BaseException as failure:
        report["status"] = "uncertain_do_not_retry"
        report["failure"] = str(failure)
        try:
            process.stdin.write(b"\n")
            process.stdin.flush()
        except OSError:
            pass
        raise
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
        save(report)
    report["after_readback"] = read_commanded_pulses("jetson-usb")
    assert report["after_readback"]["prescale"] == 121
    assert not report["after_readback"]["mode1"] & 16
    assert all(abs(report["after_readback"]["commanded_us"][j]-TARGETS[j]) <= 3 for j in TARGETS)
    report["after_capture"] = capture_to_disk("jetson-usb", ROOT)
    report["note"] = "PWM registers are commands, not joint angle measurements. Controller closed; PCA holds pulses."
    save(report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
