import json
import queue

import pytest

from premonition.arm_session import CONTROLLER_SHA256, OVERSHOOT_US, ArmSession, ArmSessionError
from premonition.teaching_hold import MotionHeld

POSITIONS = {"base": 1499, "shoulder": 1602, "elbow": 2290, "wrist_pitch": 1182, "wrist_roll": 1567, "gripper": 1616}


def ok_reply(command):
    return {"id": command["id"], "ok": True, "stopped": False, "positions": command["targets"], "error": None}


class FakeStdin:
    def __init__(self, process):
        self.process, self.data, self.closed = process, b"", False

    def write(self, data):
        self.data += data
        self.process.feed(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True
        self.process.lines.put(None)


class FakeProcess:
    def __init__(self, respond=ok_reply, ready=POSITIONS):
        self.ready, self.lines = ready, queue.Queue()
        self.lines.put(json.dumps({"id": 0, "ok": True, "positions": ready}).encode() + b"\n")
        self.respond, self.returncode = respond, None
        self.stdin = FakeStdin(self)
        self.stdout = iter(self.lines.get, None)

    def feed(self, data):
        for line in data.splitlines():
            if line.strip():
                reply = self.respond(json.loads(line))
                self.lines.put(None if reply is None else json.dumps(reply).encode() + b"\n")

    def sent(self):
        return [json.loads(line) for line in self.stdin.data.splitlines() if line.strip()]

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def terminate(self):
        self.returncode = -1


def make_session(tmp_path, process=None, mode1=33, sha=CONTROLLER_SHA256, arm_processes=()):
    calls = []
    process = process or FakeProcess()

    def popen(argv, **options):
        calls.append(argv)
        return process

    session = ArmSession("jetson-usb", tmp_path, popen=popen,
                         inventory=lambda host: {"programs": {"mindarm_arm.py": {"sha256": sha}},
                                                 "arm_processes": list(arm_processes)},
                         registers=lambda host: {"mode1": mode1, "prescale": 121, "commanded_us": dict(process.ready)})
    return session, process, calls


def test_open_refuses_reset_controller(tmp_path):
    session, _, calls = make_session(tmp_path, mode1=17)
    with pytest.raises(ArmSessionError):
        session.open()
    assert calls == []


def test_open_refuses_changed_controller_hash(tmp_path):
    session, _, calls = make_session(tmp_path, sha="0" * 64)
    with pytest.raises(ArmSessionError):
        session.open()
    assert calls == []


def test_open_refuses_motion_hold(tmp_path):
    hold = tmp_path / "real/calibration/motion_hold.json"
    hold.parent.mkdir(parents=True)
    hold.write_text("{}", encoding="utf-8")
    session, _, calls = make_session(tmp_path)
    with pytest.raises(MotionHeld):
        session.open()
    assert calls == []


def test_open_refuses_running_arm_process(tmp_path):
    session, _, calls = make_session(tmp_path, arm_processes=[{"pid": 42}])
    with pytest.raises(ArmSessionError):
        session.open()
    assert calls == []


def test_open_returns_ready_positions(tmp_path):
    session, _, calls = make_session(tmp_path)
    assert session.open() == POSITIONS
    assert session.positions == POSITIONS
    assert len(calls) == 1 and calls[0][-1] == "python3 /home/abelbrayan/mindarm_arm.py"


def test_move_fills_missing_joints_and_paces_duration(tmp_path):
    session, process, _ = make_session(tmp_path)
    session.open()
    reply = session.move({"base": POSITIONS["base"] + 300})
    command = process.sent()[0]
    assert command["cmd"] == "move" and command["duration"] == 1.0
    assert command["targets"] == dict(POSITIONS, base=1799)
    assert reply["ok"] and session.positions == dict(POSITIONS, base=1799)
    logged = [json.loads(line) for line in (tmp_path / "real/autonomy/commands.jsonl").read_text().splitlines()]
    assert logged[0]["targets"] == command["targets"] and logged[0]["duration"] == 1.0 and logged[0]["reply"]["ok"]


def test_default_duration_is_accepted_and_within_limits_for_every_step(tmp_path):
    session, _, _ = make_session(tmp_path)
    session.open()
    for step in range(1, 301):
        duration = session._check({"base": POSITIONS["base"] + step}, None)[1]
        assert duration >= 0.5 and step / duration <= 300


def test_move_rejects_limits_and_large_steps(tmp_path):
    session, process, _ = make_session(tmp_path)
    session.open()
    with pytest.raises(ValueError):
        session.move({"elbow": 2300})
    with pytest.raises(ValueError):
        session.move({"base": POSITIONS["base"] + 301})
    assert process.stdin.data == b""


def test_unchanged_joint_read_back_at_a_limit_does_not_block_other_joints(tmp_path):
    session, process, _ = make_session(tmp_path, process=FakeProcess(ready=dict(POSITIONS, elbow=2300)))
    session.open()
    session.move({"base": 1450})
    assert process.sent()[0]["targets"]["elbow"] == 2300
    session.move({"elbow": 2290})
    with pytest.raises(ValueError):
        session.move({"elbow": 2300})


def test_settle_move_approaches_from_below(tmp_path):
    session, process, _ = make_session(tmp_path, process=FakeProcess(ready=dict(POSITIONS, base=1500)))
    session.open()
    session.settle_move({"base": 1400})
    assert [c["targets"]["base"] for c in process.sent()] == [1380, 1400]
    session.settle_move({"base": 1450})
    assert [c["targets"]["base"] for c in process.sent()] == [1380, 1400, 1450]


def test_settle_move_never_overshoots_past_a_limit(tmp_path):
    session, process, _ = make_session(tmp_path, process=FakeProcess(ready=dict(POSITIONS, wrist_pitch=1300)))
    session.open()
    session.settle_move({"wrist_pitch": 1190})
    assert [c["targets"]["wrist_pitch"] for c in process.sent()] == [1181, 1190]


def test_settle_move_uses_the_per_joint_overshoot(tmp_path, monkeypatch):
    monkeypatch.setitem(OVERSHOOT_US, "shoulder", 50)
    session, process, _ = make_session(tmp_path, process=FakeProcess(ready=dict(POSITIONS, shoulder=1500)))
    session.open()
    session.settle_move({"shoulder": 1400})
    assert [c["targets"]["shoulder"] for c in process.sent()] == [1350, 1400]


def test_default_shoulder_preload_matches_the_measured_sixty_us_and_keeps_motion_limits(tmp_path):
    start = dict(POSITIONS, shoulder=1500)
    session, process, _ = make_session(tmp_path, process=FakeProcess(ready=start))
    session.open()
    session.settle_move({"shoulder": 1400})
    commands = process.sent()
    assert [c["targets"]["shoulder"] for c in commands] == [1340, 1400]
    previous = start
    for command in commands:
        step = max(abs(command["targets"][j] - previous[j]) for j in previous)
        assert step <= 300 and command["duration"] >= .5 and step / command["duration"] <= 300
        previous = command["targets"]


def test_dead_process_marks_session_unusable(tmp_path):
    session, process, _ = make_session(tmp_path, process=FakeProcess(respond=lambda command: None))
    session.open()
    with pytest.raises(ArmSessionError):
        session.move({"wrist_roll": 1597})
    written = process.stdin.data
    with pytest.raises(ArmSessionError):
        session.move({"wrist_roll": 1537})
    assert process.stdin.data == written


def test_reply_not_ok_raises_and_keeps_positions(tmp_path):
    refuse = lambda command: {"id": command["id"], "ok": False, "stopped": False, "positions": POSITIONS, "error": "x"}
    session, _, _ = make_session(tmp_path, process=FakeProcess(respond=refuse))
    session.open()
    with pytest.raises(ArmSessionError):
        session.move({"wrist_roll": 1597})
    assert session.positions == POSITIONS
