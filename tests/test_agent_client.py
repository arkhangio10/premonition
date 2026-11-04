import json
import queue
import sys
import threading
import time
from pathlib import Path

import pytest

from premonition.agent_client import AgentClient, MotionBlocked, MotionBusy, SubprocessStream

ROOT = Path(__file__).resolve().parent.parent
JOINTS = ["base", "shoulder", "elbow", "wrist_pitch", "wrist_roll", "gripper"]
HOME = {joint: 1500 for joint in JOINTS}


class ScriptedStream:
    """Enlace falso: registra lo enviado y responde según una función."""

    def __init__(self, respond):
        self.respond = respond
        self.sent = []
        self.incoming = queue.Queue()

    def send(self, line):
        message = json.loads(line)
        self.sent.append(message)
        for reply in self.respond(message) or []:
            self.incoming.put(json.dumps(reply))

    def readline(self):
        return self.incoming.get()

    def close(self):
        self.incoming.put("")

    def moves(self):
        return [m for m in self.sent if m["op"] == "move"]


def healthy(message):
    if message["op"] == "hello":
        return [{"op": "hello", "state": "idle", "backend": "fake"}]
    if message["op"] == "move":
        return [{"op": "accepted", "command_id": message["command_id"]},
                {"op": "result", "command_id": message["command_id"], "status": "completed",
                 "reason": None, "commanded_us": message["targets"]}]
    if message["op"] == "status":
        return [{"op": "status", "state": "idle", "pending": None, "record": None}]
    if message["op"] == "unlock":
        return [{"op": "unlocked", "state": "idle"}]
    return []


def client_for(respond, **options):
    stream = ScriptedStream(respond)
    client = AgentClient(lambda: stream, ack_timeout_s=0.2, result_margin_s=0.2, heartbeat_s=0.05, **options)
    client.connect()
    return client, stream


def test_completed_move_reports_the_command_id():
    client, stream = client_for(healthy)
    outcome = client.move(HOME, 0.1)
    assert outcome.status == "completed" and outcome.command_id == stream.moves()[0]["command_id"]


def test_each_move_uses_a_new_command_id():
    client, stream = client_for(healthy)
    client.move(HOME, 0.1)
    client.move(HOME, 0.1)
    first, second = stream.moves()
    assert first["command_id"] != second["command_id"]


def test_lost_result_is_unknown_and_is_never_resent():
    def silent_after_accept(message):
        if message["op"] == "move":
            return [{"op": "accepted", "command_id": message["command_id"]}]
        return healthy(message)

    client, stream = client_for(silent_after_accept)
    outcome = client.move(HOME, 0.05)
    assert outcome.status == "unknown"
    assert len(stream.moves()) == 1


def test_missing_ack_is_unknown():
    client, stream = client_for(lambda m: healthy(m) if m["op"] != "move" else [])
    assert client.move(HOME, 0.05).status == "unknown"
    assert len(stream.moves()) == 1


def test_unknown_outcome_blocks_every_later_move():
    client, stream = client_for(lambda m: healthy(m) if m["op"] != "move" else [])
    client.move(HOME, 0.05)
    with pytest.raises(MotionBlocked):
        client.move(HOME, 0.05)
    assert len(stream.moves()) == 1


def test_result_for_another_command_is_ignored():
    def wrong_id(message):
        if message["op"] == "move":
            return [{"op": "accepted", "command_id": message["command_id"]},
                    {"op": "result", "command_id": "otro", "status": "completed"}]
        return healthy(message)

    client, _ = client_for(wrong_id)
    assert client.move(HOME, 0.05).status == "unknown"


def test_second_concurrent_move_is_refused_locally():
    def slow(message):
        if message["op"] == "move":
            return [{"op": "accepted", "command_id": message["command_id"]}]
        return healthy(message)

    client, stream = client_for(slow)
    worker = threading.Thread(target=lambda: client.move(HOME, 0.3))
    worker.start()
    while not stream.moves():
        time.sleep(0.01)
    with pytest.raises(MotionBusy):
        client.move(HOME, 0.3)
    worker.join()
    assert len(stream.moves()) == 1


def test_heartbeats_flow_while_a_move_is_pending():
    def delayed(message):
        if message["op"] == "move":
            threading.Timer(0.25, lambda: stream.incoming.put(json.dumps(
                {"op": "result", "command_id": message["command_id"], "status": "completed"}))).start()
            return [{"op": "accepted", "command_id": message["command_id"]}]
        return healthy(message)

    client, stream = client_for(delayed)
    assert client.move(HOME, 0.2).status == "completed"
    assert sum(1 for m in stream.sent if m["op"] == "heartbeat") >= 2


def test_rejected_move_is_reported_and_does_not_block():
    def refuse(message):
        if message["op"] == "move":
            return [{"op": "rejected", "command_id": message["command_id"], "reason": "invalid", "detail": "x"}]
        return healthy(message)

    client, stream = client_for(refuse)
    assert client.move(HOME, 0.1).status == "rejected"
    assert client.blocked is None


def test_link_loss_during_a_move_is_unknown():
    def drop(message):
        if message["op"] == "move":
            stream.close()
            return []
        return healthy(message)

    client, stream = client_for(drop)
    assert client.move(HOME, 0.05).status == "unknown"


def test_reconnect_never_resends_and_stays_blocked_until_reconciled():
    streams = []

    def first(message):
        return healthy(message) if message["op"] != "move" else []

    def factory():
        streams.append(ScriptedStream(first))
        return streams[-1]

    client = AgentClient(factory, ack_timeout_s=0.1, result_margin_s=0.1, heartbeat_s=0.05)
    client.connect()
    client.move(HOME, 0.05)
    status = client.reconnect()
    assert status["op"] == "status"
    assert streams[1].moves() == []
    with pytest.raises(MotionBlocked):
        client.move(HOME, 0.05)
    client.reconcile("operador comprobó la postura")
    assert client.move(HOME, 0.05) is not None
    assert len(streams[1].moves()) == 1


def test_stop_returns_the_agent_acknowledgement():
    def respond(message):
        if message["op"] == "stop":
            return [{"op": "stop_ack", "was_moving": False, "command_id": None}]
        return healthy(message)

    client, _ = client_for(respond)
    assert client.stop()["was_moving"] is False


def test_stop_without_ack_is_reported_not_assumed():
    client, _ = client_for(healthy)
    assert client.stop()["op"] == "stop_unconfirmed"


def test_reconcile_without_ack_keeps_the_motion_blocked():
    client, _ = client_for(lambda m: [] if m["op"] == "unlock" else healthy(m))
    client.blocked = "resultado desconocido"
    assert client.reconcile("operador comprobó la escena") is None
    with pytest.raises(MotionBlocked):
        client.move(HOME, 0.1)


def test_full_cycle_against_the_real_agent_process(tmp_path):
    command = [sys.executable, str(ROOT / "agent" / "premonition_agent.py"), "serve", "--backend", "fake",
               "--journal", str(tmp_path / "journal.jsonl")]
    client = AgentClient(lambda: SubprocessStream(command))
    client.connect()
    outcome = client.move(HOME | {"gripper": 1560}, 0.2)
    assert outcome.status == "completed"
    assert outcome.commanded_us["gripper"] == 1560
    client.close()
