import ast
import importlib.util
import json
import queue
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AGENT_PATH = ROOT / "agent" / "premonition_agent.py"
spec = importlib.util.spec_from_file_location("premonition_agent", AGENT_PATH)
agent_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_module)

JOINTS = agent_module.JOINTS
HOME = {joint: 1500 for joint in JOINTS}


class Harness:
    def __init__(self, tmp_path, heartbeat_s=5.0, start=None, write_delay_s=0.0):
        self.replies = queue.Queue()
        self.backend = agent_module.FakeBackend(dict(start or HOME), write_delay_s=write_delay_s)
        self.journal = tmp_path / "journal.jsonl"
        self.agent = agent_module.Agent(self.backend, self.replies.put, str(self.journal), heartbeat_s=heartbeat_s)

    def send(self, **message):
        self.agent.handle_line(json.dumps(message))

    def reply(self, op, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = self.replies.get(timeout=deadline - time.monotonic())
            except queue.Empty:
                break
            if message["op"] == op:
                return message
        raise AssertionError(f"sin respuesta {op}")

    def move(self, command_id="c1", duration=0.3, **targets):
        self.send(op="move", command_id=command_id, targets=HOME | targets, duration=duration)


@pytest.fixture
def harness(tmp_path):
    made = []

    def make(**options):
        made.append(Harness(tmp_path, **options))
        return made[-1]

    yield make
    for item in made:
        item.agent.shutdown()


def test_hello_declares_the_fake_backend_and_the_hold_policy(harness):
    h = harness()
    h.send(op="hello")
    hello = h.reply("hello")
    assert hello["backend"] == "fake" and hello["disconnect_policy"] == "hold_last_pulses"


def test_move_reaches_targets_and_correlates_the_result(harness):
    h = harness()
    h.move(gripper=1600)
    assert h.reply("accepted")["command_id"] == "c1"
    result = h.reply("result")
    assert (result["command_id"], result["status"]) == ("c1", "completed")
    assert h.backend.positions["gripper"] == 1600


def test_only_changed_joints_receive_writes(harness):
    h = harness()
    h.move(gripper=1600)
    h.reply("result")
    assert {channel for channel, _ in h.backend.writes} == {JOINTS.index("gripper")}


def test_second_move_is_rejected_while_one_is_pending(harness):
    h = harness()
    h.move("c1", duration=0.6, gripper=1700)
    h.reply("accepted")
    h.move("c2", duration=0.6, base=1700)
    rejected = h.reply("rejected")
    assert (rejected["command_id"], rejected["reason"]) == ("c2", "busy")
    assert h.reply("result")["status"] == "completed"
    assert h.backend.positions["base"] == 1500


def test_status_during_a_ramp_does_not_interrupt_it(harness):
    h = harness()
    h.move(duration=0.4, gripper=1700)
    h.reply("accepted")
    h.send(op="status")
    assert h.reply("status")["pending"] == "c1"
    assert h.reply("result")["status"] == "completed"
    assert h.backend.positions["gripper"] == 1700


def test_heartbeat_during_a_ramp_does_not_interrupt_it(harness):
    h = harness()
    h.move(duration=0.4, gripper=1700)
    h.reply("accepted")
    h.send(op="heartbeat")
    h.send(op="heartbeat")
    assert h.reply("result")["status"] == "completed"


def test_duplicate_command_id_never_moves_again(harness):
    h = harness()
    h.move("c1", gripper=1600)
    h.reply("result")
    h.move("c1", base=1600)
    rejected = h.reply("rejected")
    assert rejected["reason"] == "duplicate" and rejected["previous"]["status"] == "completed"
    assert h.backend.positions["base"] == 1500


def test_stop_during_a_ramp_holds_the_last_pulse_and_reports_it(harness):
    h = harness()
    h.move(duration=1.0, gripper=1900)
    h.reply("accepted")
    time.sleep(0.15)
    h.send(op="stop")
    ack = h.reply("stop_ack")
    assert ack["was_moving"] is True and ack["command_id"] == "c1"
    result = h.reply("result")
    assert (result["status"], result["reason"]) == ("stopped", "operator_stop")
    assert 1500 < h.backend.positions["gripper"] < 1900


def test_stop_while_idle_is_acknowledged(harness):
    h = harness()
    h.send(op="stop")
    assert h.reply("stop_ack")["was_moving"] is False


def test_unknown_operation_is_an_error_and_moves_nothing(harness):
    h = harness()
    h.send(op="i2c_write", channel=5, us=1950)
    assert "unknown op" in h.reply("error")["error"]
    assert h.backend.writes == []


def test_invalid_json_is_an_error(harness):
    h = harness()
    h.agent.handle_line("{no json")
    assert h.reply("error")


@pytest.mark.parametrize("change, fragment", [
    (lambda t: t.pop("gripper"), "exactly"),
    (lambda t: t.update(gripper=2500), "outside"),
    (lambda t: t.update(wrist_pitch=1100), "outside"),
    (lambda t: t.update(gripper=1500.5), "integer"),
    (lambda t: t.update(gripper=True), "integer"),
    (lambda t: t.update(extra=1500), "exactly"),
])
def test_targets_outside_the_contract_are_rejected(harness, change, fragment):
    h = harness()
    targets = dict(HOME)
    change(targets)
    h.send(op="move", command_id="c1", targets=targets, duration=1.0)
    rejected = h.reply("rejected")
    assert rejected["reason"] == "invalid" and fragment in rejected["detail"]
    assert h.backend.writes == []


@pytest.mark.parametrize("duration", [0, -1, 11, "2", True, None])
def test_invalid_durations_are_rejected(harness, duration):
    h = harness()
    h.send(op="move", command_id="c1", targets=dict(HOME), duration=duration)
    assert h.reply("rejected")["reason"] == "invalid"


def test_speed_above_the_cap_is_rejected(harness):
    h = harness()
    h.move(duration=0.1, gripper=1900)
    rejected = h.reply("rejected")
    assert rejected["reason"] == "invalid" and "speed" in rejected["detail"]


def test_released_channel_is_rejected_instead_of_energized(harness):
    h = harness(start=HOME | {"elbow": None})
    h.move(gripper=1600)
    rejected = h.reply("rejected")
    assert rejected["reason"] == "invalid" and "released" in rejected["detail"]
    assert h.backend.writes == []


def test_silent_link_stops_the_ramp_and_locks_new_moves(harness):
    h = harness(heartbeat_s=0.15)
    h.move(duration=2.0, gripper=1900)
    h.reply("accepted")
    result = h.reply("result")
    assert (result["status"], result["reason"]) == ("stopped", "heartbeat_lost")
    held = h.backend.positions["gripper"]
    h.move("c2", duration=0.3, base=1600)
    assert h.reply("rejected")["reason"] == "locked"
    assert h.backend.positions["gripper"] == held and h.backend.positions["base"] == 1500


def test_unlock_requires_an_explicit_message_and_allows_a_new_id(harness):
    h = harness(heartbeat_s=0.1)
    h.move(duration=2.0, gripper=1900)
    h.reply("result")
    h.send(op="unlock", note="operador reconcilió la escena")
    assert h.reply("unlocked")["state"] == "idle"


def test_overrunning_a_deadline_stops_and_locks(harness):
    h = harness(write_delay_s=0.5, heartbeat_s=30.0)
    h.agent.deadline_margin_s = 0.0
    h.move(duration=0.2, gripper=1550)
    result = h.reply("result", timeout=5.0)
    assert (result["status"], result["reason"]) == ("stopped", "deadline")
    h.send(op="status")
    assert h.reply("status")["state"] == "locked"


def test_journal_records_acceptance_before_any_write(harness):
    h = harness()
    h.move(gripper=1600)
    h.reply("result")
    lines = [json.loads(line) for line in h.journal.read_text(encoding="utf-8").splitlines()]
    assert [line["phase"] for line in lines] == ["accepted", "finished"]


def test_restart_rejects_commands_seen_before_the_restart(tmp_path):
    first = Harness(tmp_path)
    first.move("c1", gripper=1600)
    first.reply("result")
    first.agent.shutdown()
    second = Harness(tmp_path)
    second.move("c1", gripper=1700)
    assert second.reply("rejected")["reason"] == "duplicate"
    assert second.backend.writes == []
    second.agent.shutdown()


def test_restart_after_an_unfinished_command_starts_locked(tmp_path):
    (tmp_path / "journal.jsonl").write_text(
        json.dumps({"phase": "accepted", "command_id": "c9"}) + "\n", encoding="utf-8")
    h = Harness(tmp_path)
    h.send(op="status", command_id="c9")
    status = h.reply("status")
    assert status["state"] == "locked" and status["record"]["status"] == "unknown"
    h.move("c10", gripper=1600)
    assert h.reply("rejected")["reason"] == "locked"
    h.agent.shutdown()


def test_restart_preserves_a_watchdog_lock(tmp_path):
    entries = [{"phase": "accepted", "command_id": "c1"},
               {"phase": "finished", "command_id": "c1", "record": {
                   "status": "stopped", "reason": "heartbeat_lost", "commanded_us": HOME}}]
    (tmp_path / "journal.jsonl").write_text("\n".join(map(json.dumps, entries)) + "\n", encoding="utf-8")
    h = Harness(tmp_path)
    h.move("c2", gripper=1600)
    assert h.reply("rejected")["reason"] == "locked"
    assert h.backend.writes == []
    h.agent.shutdown()


def test_acknowledged_reconciliation_survives_restart_but_ids_stay_used(tmp_path):
    (tmp_path / "journal.jsonl").write_text(
        json.dumps({"phase": "accepted", "command_id": "c1"}) + "\n", encoding="utf-8")
    first = Harness(tmp_path)
    first.send(op="unlock", note="operador comprobó la escena")
    assert first.reply("unlocked")["state"] == "idle"
    first.agent.shutdown()
    second = Harness(tmp_path)
    second.send(op="status")
    assert second.reply("status")["state"] == "idle"
    second.move("c1", gripper=1600)
    assert second.reply("rejected")["reason"] == "duplicate"
    second.agent.shutdown()


def serve(tmp_path, *extra):
    command = [sys.executable, str(AGENT_PATH), "serve", "--backend", "fake",
               "--journal", str(tmp_path / "journal.jsonl"), *extra]
    return subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)


def test_end_of_input_stops_the_ramp_exits_and_records_it(tmp_path):
    process = serve(tmp_path)
    process.stdin.write(json.dumps({"op": "move", "command_id": "c1", "targets": HOME | {"gripper": 1900},
                                    "duration": 3.0}) + "\n")
    process.stdin.flush()
    assert json.loads(process.stdout.readline())["op"] == "accepted"
    time.sleep(0.1)
    process.stdin.close()
    remaining = process.stdout.read().strip().splitlines()
    assert process.wait(timeout=5) == 0
    result = json.loads(remaining[-1])
    assert (result["status"], result["reason"]) == ("stopped", "disconnected")
    assert result["commanded_us"]["gripper"] < 1900


AGENT_SOURCES = ["premonition_agent.py", "capture_once.py", "read_registers.py"]


@pytest.mark.parametrize("name", AGENT_SOURCES)
def test_jetson_scripts_parse_with_python_36_grammar(name):
    ast.parse((ROOT / "agent" / name).read_text(encoding="utf-8"), feature_version=(3, 6))


def imports_of(name):
    tree = ast.parse((ROOT / "agent" / name).read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add((node.module or "").split(".")[0])
    return found


def test_motion_agent_has_no_path_to_i2c():
    assert not imports_of("premonition_agent.py") & {"smbus", "smbus2", "fcntl", "ctypes", "subprocess"}


def test_capture_script_never_touches_the_motor_controller():
    assert not imports_of("capture_once.py") & {"smbus", "smbus2", "subprocess"}


def test_register_reader_contains_no_write_call():
    tree = ast.parse((ROOT / "agent" / "read_registers.py").read_text(encoding="utf-8"))
    calls = {node.func.attr for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not {c for c in calls if c.startswith("write")}
