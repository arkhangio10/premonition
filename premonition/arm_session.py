"""One controller process held open for a whole autonomy session, with the PC-side motion limits."""
import json
import math
import queue
import subprocess
import threading
import time
from pathlib import Path

from .jetson import inspect_system, read_commanded_pulses, ssh_argv
from .teaching_hold import require_no_motion_hold

LIMITS_US = {"base": (1000, 2000), "shoulder": (1000, 2000), "elbow": (1000, 2300),
             "wrist_pitch": (1180, 1980), "wrist_roll": (1000, 2000), "gripper": (1130, 1950)}
CONTROLLER_SHA256 = "2ab17e54cf8832712f3f1620815964ddeb45172cd68bc55e84e31a8c8a5d0040"
CONTROLLER_COMMAND = "python3 /home/abelbrayan/mindarm_arm.py"
MAX_DELTA_US = 300
OVERSHOOT_US = {joint: 20 for joint in LIMITS_US}
MAX_SPEED_US_S = 300.0
MIN_DURATION_S = 0.5
MAX_DURATION_S = 10.0


class ArmSessionError(RuntimeError):
    pass


class ArmSession:
    def __init__(self, host: str, root: Path, popen=subprocess.Popen, inventory=inspect_system,
                 registers=read_commanded_pulses):
        self.host, self.root = host, Path(root)
        self.popen, self.inventory, self.registers = popen, inventory, registers
        self.process, self.positions, self.dead, self.next_id = None, {}, False, 1
        self.replies = queue.Queue()
        self.log_path = self.root / "real/autonomy/commands.jsonl"

    def open(self) -> dict:
        require_no_motion_hold(self.root)
        inventory = self.inventory(self.host)
        if inventory["programs"]["mindarm_arm.py"]["sha256"] != CONTROLLER_SHA256:
            raise ArmSessionError("Controller source changed; review it before opening a session.")
        if inventory["arm_processes"]:
            raise ArmSessionError(f"Another arm process is running: {inventory['arm_processes']}")
        reading = self.registers(self.host)
        pulses = reading["commanded_us"]
        if reading["mode1"] != 33 or reading["prescale"] != 121:
            raise ArmSessionError(f"PCA not configured (MODE1={reading['mode1']}, PRESCALE={reading['prescale']}); "
                                  "restart at the pose seen in the photos, not at HOME.")
        if set(pulses) != set(LIMITS_US) or any(type(v) is not int for v in pulses.values()):
            raise ArmSessionError(f"Released or unknown channels: {pulses}")
        self.process = self.popen(ssh_argv(self.host, CONTROLLER_COMMAND),
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        threading.Thread(target=self._read, daemon=True).start()
        try:
            ready = self.replies.get(timeout=15)
        except queue.Empty:
            ready = None
        if not ready or ready.get("id") != 0 or ready.get("ok") is not True or ready.get("positions") != pulses:
            self.dead = True
            self.close()
            raise ArmSessionError(f"Controller start differs from the register readback: {ready}")
        self.positions = dict(ready["positions"])
        return dict(self.positions)

    def _read(self):
        for line in self.process.stdout:
            try:
                self.replies.put(json.loads(line))
            except ValueError:
                self.replies.put({"ok": False, "error": f"unparsable reply: {line!r}"})
        self.replies.put(None)

    def _check(self, targets: dict, duration: float | None) -> tuple[dict, float]:
        if self.dead or self.process is None:
            raise ArmSessionError("Session is not usable; read the registers before deciding anything.")
        if set(targets) - set(LIMITS_US):
            raise ValueError(f"Unknown joints: {sorted(set(targets) - set(LIMITS_US))}")
        full = dict(self.positions, **targets)
        for joint, value in full.items():
            low, high = LIMITS_US[joint]
            if value != self.positions[joint] and (type(value) is not int or not low < value < high):
                raise ValueError(f"{joint}={value} outside ({low}, {high})")
        step = max(abs(full[j] - self.positions[j]) for j in full)
        if step > MAX_DELTA_US:
            raise ValueError(f"Step of {step} us exceeds {MAX_DELTA_US} us")
        if duration is None:
            duration = max(MIN_DURATION_S, math.ceil(step / MAX_SPEED_US_S * 1000 - 1e-9) / 1000)
        duration = round(duration, 3)
        if not MIN_DURATION_S <= duration <= MAX_DURATION_S or step / duration > MAX_SPEED_US_S:
            raise ValueError(f"Duration {duration} s outside limits for a {step} us step")
        return full, duration

    def move(self, targets: dict, duration: float | None = None) -> dict:
        full, duration = self._check(targets, duration)
        command = {"id": self.next_id, "cmd": "move", "targets": full, "duration": duration}
        self.next_id += 1
        try:
            self.process.stdin.write((json.dumps(command) + "\n").encode())
            self.process.stdin.flush()
            reply = self.replies.get(timeout=duration + 5)
        except (OSError, queue.Empty) as failure:
            reply = {"ok": False, "error": f"no reply: {failure!r}"}
            self._interrupt()
        self._log(command, reply)
        if reply is None or reply.get("id") != command["id"]:
            self.dead = True
            raise ArmSessionError(f"Controller ended or answered out of order: {reply}")
        if reply.get("ok") is not True or reply.get("stopped") or reply.get("positions") != full:
            self.dead = True
            raise ArmSessionError(f"Move not acknowledged: {reply}")
        self.positions = dict(reply["positions"])
        return reply

    def settle_move(self, targets: dict, overshoot_us: int | None = None) -> dict:
        full = dict(self.positions, **targets)
        via = {j: max(v - (OVERSHOOT_US[j] if overshoot_us is None else overshoot_us), LIMITS_US[j][0] + 1)
               if v < self.positions[j] else v for j, v in full.items()}
        if via != full:
            self.move(via)
        return self.move(full)

    def _interrupt(self):
        self.dead = True
        try:
            self.process.stdin.write(b"\n")
            self.process.stdin.flush()
        except OSError:
            pass

    def _log(self, command: dict, reply):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"t": time.time(), "targets": command["targets"],
                                  "duration": command["duration"], "reply": reply}) + "\n")

    def close(self):
        if self.process is None:
            return
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)
        self.process = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()
