#!/usr/bin/env python3
"""Agente de movimiento acotado para la Jetson: JSON por líneas en stdin/stdout (Python 3.6).

Corrige limitaciones de mindarm_arm.py sin sustituirlo: una sola orden pendiente, IDs
correlacionados, rechazo de duplicados, status y heartbeat que no interrumpen la rampa, stop con
ACK, watchdog de enlace y diario en disco para reconciliar tras un corte.

Esta entrega solo incluye FakeBackend: este archivo no tiene ningún camino hacia I2C.
Al desconectar mantiene los últimos pulsos: no corta el par para no dejar caer brazo o carga.
"""
import argparse
import json
import os
import signal
import sys
import threading
import time
import uuid

JOINTS = ["base", "shoulder", "elbow", "wrist_pitch", "wrist_roll", "gripper"]  # índice = canal
# Envolvente copiada de mindarm_arm.py: límite previo, no calibración revalidada.
LIMITS_US = {"base": (1000, 2000), "shoulder": (1000, 2000), "elbow": (1000, 2000),
             "wrist_pitch": (1180, 1980), "wrist_roll": (1000, 2000), "gripper": (1130, 2100)}
MAX_SPEED_US_S = 1000.0
MAX_DURATION_S = 10.0
STEP_S = 0.02
DISCONNECT_POLICY = "hold_last_pulses"
UNSAFE_REASONS = ("heartbeat_lost", "deadline", "disconnected")


class FakeBackend(object):
    """Backend de prueba. Sus pulsos iniciales son ficticios y no describen el brazo real."""

    name = "fake"

    def __init__(self, positions=None, write_delay_s=0.0):
        self.positions = dict(positions) if positions else {joint: 1500 for joint in JOINTS}
        self.write_delay_s = write_delay_s
        self.writes = []

    def read_us(self, channel):
        return self.positions[JOINTS[channel]]

    def write_us(self, channel, us):
        time.sleep(self.write_delay_s)
        self.positions[JOINTS[channel]] = us
        self.writes.append((channel, us))


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_move(targets, duration, start):
    """Devuelve el motivo de rechazo de una orden, o None si respeta el contrato."""
    if not isinstance(targets, dict) or set(targets) != set(JOINTS):
        return "targets must name exactly: " + ", ".join(JOINTS)
    if not is_number(duration) or not 0 < duration <= MAX_DURATION_S:
        return "duration must be in (0, {}] s".format(MAX_DURATION_S)
    for joint in JOINTS:
        value, (low, high), current = targets[joint], LIMITS_US[joint], start[joint]
        if not isinstance(value, int) or isinstance(value, bool):
            return "{}: target must be an integer of us".format(joint)
        if not low <= value <= high:
            return "{}: {} us outside [{}, {}]".format(joint, value, low, high)
        if current is None:
            return "{} is released; this agent never energizes a channel".format(joint)
        if abs(value - current) / float(duration) > MAX_SPEED_US_S:
            return "{}: speed exceeds {} us/s".format(joint, MAX_SPEED_US_S)
    return None


class Agent(object):
    def __init__(self, backend, write, journal_path, heartbeat_s=1.0):
        self.backend, self.write = backend, write
        self.journal_path, self.heartbeat_s = journal_path, heartbeat_s
        self.deadline_margin_s = 2.0
        self.session = uuid.uuid4().hex
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.stop_reason = None
        self.pending = None
        self.worker = None
        self.records = {}
        self.locked = None
        self.last_seen = time.monotonic()
        self._load_journal()

    def _load_journal(self):
        if not os.path.exists(self.journal_path):
            return
        with open(self.journal_path) as stream:
            for line in stream:
                entry = json.loads(line)
                if entry["phase"] == "accepted":
                    self.records[entry["command_id"]] = {"status": "unknown", "reason": "no_result_recorded"}
                elif entry["phase"] == "finished":
                    self.records[entry["command_id"]] = entry["record"]
                elif entry["phase"] == "unlocked":
                    self.locked = None
                    for record in self.records.values():
                        if record["status"] == "unknown":
                            record["status"] = "reconciled"
                if entry["phase"] == "finished":
                    record = entry["record"]
                    if record["status"] == "failed" or record.get("reason") in UNSAFE_REASONS:
                        self.locked = "{} after {}".format(record.get("reason"), entry["command_id"])
        unresolved = [c for c, r in self.records.items() if r["status"] == "unknown"]
        if unresolved:
            self.locked = "unresolved command: " + ", ".join(unresolved)

    def _journal(self, entry):
        with open(self.journal_path, "a") as stream:
            stream.write(json.dumps(entry) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _commanded(self):
        return {joint: self.backend.read_us(channel) for channel, joint in enumerate(JOINTS)}

    def _state(self):
        if self.pending:
            return "moving"
        return "locked" if self.locked else "idle"

    def handle_line(self, line):
        self.last_seen = time.monotonic()
        try:
            message = json.loads(line)
        except ValueError as error:
            self.write({"op": "error", "error": "invalid JSON: {}".format(error)})
            return
        handlers = {"hello": self._hello, "status": self._status, "heartbeat": self._heartbeat,
                    "move": self._move, "stop": self._stop, "unlock": self._unlock}
        handler = handlers.get(message.get("op")) if isinstance(message, dict) else None
        if handler is None:
            self.write({"op": "error", "error": "unknown op: {!r}".format(message)})
            return
        handler(message)

    def _hello(self, message):
        self.write({"op": "hello", "session": self.session, "backend": self.backend.name,
                    "state": self._state(), "locked": self.locked, "disconnect_policy": DISCONNECT_POLICY})

    def _status(self, message):
        self.write({"op": "status", "state": self._state(), "pending": self.pending, "locked": self.locked,
                    "commanded_us": self._commanded(), "record": self.records.get(message.get("command_id"))})

    def _heartbeat(self, message):
        self.write({"op": "heartbeat_ack", "state": self._state()})

    def _refusal(self, command_id, message, start):
        if not isinstance(command_id, str) or not command_id:
            return {"reason": "invalid", "detail": "command_id must be a non-empty string"}
        if command_id in self.records:
            return {"reason": "duplicate", "previous": self.records[command_id]}
        if self.locked:
            return {"reason": "locked", "detail": self.locked}
        if self.pending:
            return {"reason": "busy", "pending": self.pending}
        detail = check_move(message.get("targets"), message.get("duration"), start)
        return {"reason": "invalid", "detail": detail} if detail else None

    def _move(self, message):
        command_id = message.get("command_id")
        with self.lock:
            start = self._commanded()
            refusal = self._refusal(command_id, message, start)
            if refusal:
                if isinstance(command_id, str) and command_id and refusal["reason"] != "duplicate":
                    self.records[command_id] = {"status": "rejected", "reason": refusal["reason"]}
                self.write(dict(refusal, op="rejected", command_id=command_id))
                return
            self.pending = command_id
            self.stop_event.clear()
            self.stop_reason = None
            self.records[command_id] = {"status": "unknown", "reason": "in_progress"}
            self._journal({"phase": "accepted", "command_id": command_id, "session": self.session,
                           "targets": message["targets"], "duration": message["duration"], "start": start})
        self.write({"op": "accepted", "command_id": command_id})
        self.worker = threading.Thread(target=self._ramp, args=(command_id, start, message["targets"],
                                                                message["duration"]))
        self.worker.daemon = True
        self.worker.start()

    def _interruption(self, deadline):
        if self.stop_event.wait(STEP_S):
            return self.stop_reason
        now = time.monotonic()
        if now - self.last_seen > self.heartbeat_s:
            return "heartbeat_lost"
        return "deadline" if now > deadline else None

    def _ramp(self, command_id, start, targets, duration):
        status, reason = "completed", None
        current = dict(start)
        moving = [joint for joint in JOINTS if targets[joint] != start[joint]]
        began = time.monotonic()
        deadline = began + duration + self.deadline_margin_s
        try:
            while moving:
                fraction = min(1.0, (time.monotonic() - began) / duration)
                for joint in moving:
                    value = int(round(start[joint] + (targets[joint] - start[joint]) * fraction))
                    if value != current[joint]:
                        self.backend.write_us(JOINTS.index(joint), value)
                        current[joint] = value
                if fraction >= 1.0:
                    break
                reason = self._interruption(deadline)
                if reason:
                    status = "stopped"
                    break
        except Exception as error:
            status, reason = "failed", str(error)
        self._finish(command_id, status, reason, current)

    def _finish(self, command_id, status, reason, current):
        record = {"status": status, "reason": reason, "commanded_us": current}
        with self.lock:
            self.records[command_id] = record
            self.pending = None
            self._journal({"phase": "finished", "command_id": command_id, "record": record})
            if status == "failed" or reason in UNSAFE_REASONS:
                self.locked = "{} after {}".format(reason, command_id)
        self.write(dict(record, op="result", command_id=command_id))

    def _stop(self, message):
        moving = self.pending
        self._interrupt("operator_stop")
        self.write({"op": "stop_ack", "was_moving": moving is not None, "command_id": moving})

    def _interrupt(self, reason):
        self.stop_reason = reason
        self.stop_event.set()

    def _unlock(self, message):
        if self.pending:
            self.write({"op": "error", "error": "cannot unlock while a command is pending"})
            return
        if not isinstance(message.get("note"), str) or not message["note"].strip():
            self.write({"op": "error", "error": "operator reconciliation note required"})
            return
        self._journal({"phase": "unlocked", "session": self.session, "note": message.get("note"),
                       "previous": self.locked})
        self.locked = None
        for record in self.records.values():
            if record["status"] == "unknown":
                record["status"] = "reconciled"
        self.write({"op": "unlocked", "state": self._state()})

    def shutdown(self):
        """Fin de entrada: detiene la rampa y mantiene los últimos pulsos."""
        self._interrupt("disconnected")
        if self.worker is not None:
            self.worker.join()


def serve(args):
    write_lock = threading.Lock()

    def write(message):
        with write_lock:
            sys.stdout.write(json.dumps(message) + "\n")
            sys.stdout.flush()

    agent = Agent(FakeBackend(), write, args.journal, heartbeat_s=args.heartbeat_s)
    for name in ("SIGHUP", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: sys.exit(0))
    try:
        while True:
            line = sys.stdin.readline()
            if not line:
                return
            if line.strip():
                agent.handle_line(line)
    finally:
        agent.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command")
    runner = commands.add_parser("serve")
    runner.add_argument("--backend", choices=["fake"], required=True)
    runner.add_argument("--journal", required=True)
    runner.add_argument("--heartbeat-s", type=float, default=1.0)
    args = parser.parse_args()
    if args.command != "serve":
        parser.error("use: serve --backend fake --journal PATH")
    serve(args)


if __name__ == "__main__":
    main()
