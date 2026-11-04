import base64
import json
import subprocess

import pytest

from premonition.first_motion import CardRefused, build_card
from premonition.jetson import CameraError, JetsonCamera, SSH_EXE, read_commanded_pulses, ssh_argv, inspect_system
from premonition.models import CaptureRequest

TOKEN = "0" * 32
REQUEST = CaptureRequest(run_id="r", step_id="s1", attempt=1, phase="inspect", command_id=None, token=TOKEN)
PULSES = {"base": 1500, "shoulder": 1500, "elbow": 1500, "wrist_pitch": 1500, "wrist_roll": 1500, "gripper": 1500}


class FakeRun:
    def __init__(self, stdout="", returncode=0, stderr=b""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout.encode(), self.stderr)


def capture_reply(**overrides):
    reply = {"ok": True, "token": TOKEN, "width": 1920, "height": 1080, "good_reads": 8, "reads": 8,
             "elapsed_s": 1.2, "jpeg_b64": base64.b64encode(b"\xff\xd8jpeg").decode()}
    return json.dumps(reply | overrides)


def test_ssh_uses_native_client_and_keeps_host_verification():
    argv = ssh_argv("jetson-usb", "hostname")
    assert argv[0] == SSH_EXE == r"C:\Windows\System32\OpenSSH\ssh.exe"
    assert "StrictHostKeyChecking=yes" in argv and "BatchMode=yes" in argv
    assert not any("StrictHostKeyChecking=no" in part or "accept-new" in part for part in argv)


def test_capture_sends_the_script_over_stdin_with_lf_only():
    run = FakeRun(capture_reply())
    JetsonCamera("jetson-usb", run=run).capture(REQUEST)
    argv, kwargs = run.calls[0]
    assert b"\r\n" not in kwargs["input"] and b"VideoCapture" in kwargs["input"]
    assert argv[-1] == f"python3 - --token {TOKEN}"


def test_capture_never_mentions_the_servo_programs():
    run = FakeRun(capture_reply())
    JetsonCamera("jetson-usb", run=run).capture(REQUEST)
    argv, kwargs = run.calls[0]
    text = " ".join(argv) + kwargs["input"].decode()
    assert "mindarm" not in text and "servo_test" not in text and "smbus" not in text


def test_capture_returns_a_frame_stamped_with_the_echoed_token():
    frame = JetsonCamera("jetson-usb", run=FakeRun(capture_reply())).capture(REQUEST)
    assert frame.source == "jetson" and frame.token == TOKEN and frame.jpeg == b"\xff\xd8jpeg"


def test_token_from_the_jetson_is_not_replaced_by_the_requested_one():
    frame = JetsonCamera("jetson-usb", run=FakeRun(capture_reply(token="1" * 32))).capture(REQUEST)
    assert frame.token == "1" * 32


def test_capture_failure_is_raised_with_the_ssh_error():
    with pytest.raises(CameraError, match="Connection timed out"):
        JetsonCamera("h", run=FakeRun(returncode=255, stderr=b"ssh: Connection timed out")).capture(REQUEST)


def test_camera_without_frame_is_raised():
    reply = json.dumps({"ok": False, "token": TOKEN, "error": "camera returned no frame"})
    with pytest.raises(CameraError, match="no frame"):
        JetsonCamera("h", run=FakeRun(reply, returncode=1)).capture(REQUEST)


def test_capture_refuses_tokens_that_are_not_plain_hex():
    bad = REQUEST.model_copy(update={"token": "x; rm -rf /"})
    run = FakeRun(capture_reply())
    with pytest.raises(CameraError):
        JetsonCamera("h", run=run).capture(bad)
    assert run.calls == []


def test_register_read_uses_the_read_only_script():
    reading = {"mode1": 33, "prescale": 121, "commanded_us": PULSES}
    run = FakeRun(json.dumps(reading))
    assert read_commanded_pulses("h", run=run) == reading
    argv, kwargs = run.calls[0]
    assert argv[-1] == "python3 -" and b"read_byte_data" in kwargs["input"] and b"write_" not in kwargs["input"]


def test_system_inventory_reads_source_without_importing_arm_programs():
    run = FakeRun(json.dumps({"hostname": "fake", "programs": {}}))
    assert inspect_system("h", run=run)["hostname"] == "fake"
    argv, kwargs = run.calls[0]
    assert argv[-1] == "python3 -"
    assert b"ast.parse" in kwargs["input"] and b"ast.literal_eval" in kwargs["input"]
    assert b"import smbus" not in kwargs["input"] and b"subprocess" not in kwargs["input"]


def reading(**overrides):
    return {"mode1": 33, "prescale": 121, "commanded_us": dict(PULSES)} | overrides


def test_card_moves_only_the_gripper_and_keeps_the_rest_at_the_read_pulses(real_cell):
    card = build_card(reading(), real_cell)
    move = json.loads(card["command_line"])
    assert move["cmd"] == "move" and set(move["targets"]) == set(PULSES)
    assert {j for j in PULSES if move["targets"][j] != PULSES[j]} == {"gripper"}


def test_card_steps_toward_the_center_of_the_envelope(real_cell):
    low = build_card(reading(commanded_us=PULSES | {"gripper": 1200}), real_cell)
    high = build_card(reading(commanded_us=PULSES | {"gripper": 1900}), real_cell)
    assert json.loads(low["command_line"])["targets"]["gripper"] > 1200
    assert json.loads(high["command_line"])["targets"]["gripper"] < 1900


def test_card_stays_far_below_the_speed_cap(real_cell):
    card = build_card(reading(), real_cell)
    assert card["speed_us_s"] <= real_cell.max_speed_us_s * 0.05


@pytest.mark.parametrize("change, fragment", [
    ({"prescale": 100}, "prescale"),
    ({"mode1": 0x31}, "SLEEP"),
    ({"mode1": 0x01}, "AUTO_INCREMENT"),
])
def test_card_is_refused_when_the_existing_service_would_write_registers(real_cell, change, fragment):
    with pytest.raises(CardRefused, match=fragment):
        build_card(reading(**change), real_cell)


def test_card_is_refused_when_a_channel_is_released(real_cell):
    with pytest.raises(CardRefused, match="elbow"):
        build_card(reading(commanded_us=PULSES | {"elbow": None}), real_cell)


def test_card_is_refused_outside_the_envelope(real_cell):
    with pytest.raises(CardRefused, match="gripper"):
        build_card(reading(commanded_us=PULSES | {"gripper": 2100}), real_cell)


def test_card_states_what_stop_really_does(real_cell):
    text = json.dumps(build_card(reading(), real_cell), ensure_ascii=False)
    assert "Enter" in text and "no es un paro de emergencia" in text
    assert "alimentación" in text
