"""Cliente del agente de la Jetson: una orden a la vez y nunca reenvía tras un resultado dudoso."""
import json
import queue
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field


class MotionBlocked(RuntimeError):
    """Hay un resultado sin resolver; solo el operador puede levantar el bloqueo."""


class MotionBusy(RuntimeError):
    """Ya existe una orden pendiente."""


@dataclass
class AgentOutcome:
    command_id: str
    status: str
    detail: str = ""
    commanded_us: dict = field(default_factory=dict)


class SubprocessStream:
    def __init__(self, argv: list[str]):
        self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)

    def send(self, line: str):
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()

    def readline(self) -> str:
        return self.process.stdout.readline()

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=5)


class AgentClient:
    def __init__(self, open_stream, ack_timeout_s=2.0, result_margin_s=2.0, heartbeat_s=0.2):
        self.open_stream = open_stream
        self.ack_timeout_s, self.result_margin_s, self.heartbeat_s = ack_timeout_s, result_margin_s, heartbeat_s
        self.motion_lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.blocked: str | None = None
        self.last_command_id: str | None = None
        self.stream = None

    def _open(self):
        self.stream = self.open_stream()
        self.motion_inbox, self.control_inbox = queue.Queue(), queue.Queue()
        threading.Thread(target=self._read, args=(self.stream, self.motion_inbox, self.control_inbox),
                         daemon=True).start()

    @staticmethod
    def _read(stream, motion_inbox, control_inbox):
        while True:
            line = stream.readline()
            if not line:
                motion_inbox.put(None)
                return
            message = json.loads(line)
            inbox = motion_inbox if message.get("op") in ("accepted", "rejected", "result") else control_inbox
            inbox.put(message)

    def _send(self, **message) -> bool:
        try:
            with self.send_lock:
                self.stream.send(json.dumps(message))
            return True
        except (OSError, ValueError):
            return False

    def _control(self, op: str) -> dict | None:
        deadline = time.monotonic() + self.ack_timeout_s
        while True:
            try:
                message = self.control_inbox.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                return None
            if message.get("op") == op:
                return message

    def connect(self) -> dict | None:
        self._open()
        self._send(op="hello")
        hello = self._control("hello")
        if hello and hello.get("state") == "locked":
            self.blocked = f"el agente está bloqueado: {hello.get('locked')}"
        return hello

    def close(self):
        if self.stream is not None:
            self.stream.close()

    def status(self, command_id: str | None = None) -> dict | None:
        self._send(op="status", command_id=command_id)
        return self._control("status")

    def stop(self) -> dict:
        sent = self._send(op="stop")
        reply = self._control("stop_ack") if sent else None
        return reply or {"op": "stop_unconfirmed"}

    def reconnect(self) -> dict | None:
        """Abre un enlace nuevo y consulta el diario. No repite ninguna orden."""
        self.close()
        self._open()
        self._send(op="hello")
        self._control("hello")
        return self.status(self.last_command_id)

    def reconcile(self, note: str) -> dict | None:
        """El operador confirmó la escena: levanta el bloqueo local y pide levantar el del agente."""
        self._send(op="unlock", note=note)
        reply = self._control("unlocked")
        if reply and reply.get("state") == "idle":
            self.blocked = None
        return reply

    def _unknown(self, command_id: str, detail: str) -> AgentOutcome:
        self.blocked = f"resultado desconocido de {command_id}: {detail}"
        return AgentOutcome(command_id, "unknown", detail)

    def move(self, targets: dict, duration: float) -> AgentOutcome:
        if not self.motion_lock.acquire(blocking=False):
            raise MotionBusy("ya hay una orden pendiente")
        try:
            if self.blocked:
                raise MotionBlocked(self.blocked)
            command_id = uuid.uuid4().hex
            self.last_command_id = command_id
            if not self._send(op="move", command_id=command_id, targets=targets, duration=duration):
                return self._unknown(command_id, "no se pudo escribir en el enlace")
            return self._await(command_id, duration)
        finally:
            self.motion_lock.release()

    def _await(self, command_id: str, duration: float) -> AgentOutcome:
        deadline = time.monotonic() + self.ack_timeout_s
        next_beat = time.monotonic() + self.heartbeat_s
        while True:
            now = time.monotonic()
            if now >= deadline:
                return self._unknown(command_id, "venció el plazo sin resultado")
            if now >= next_beat:
                self._send(op="heartbeat")
                next_beat = now + self.heartbeat_s
            try:
                message = self.motion_inbox.get(timeout=max(0.0, min(deadline, next_beat) - now))
            except queue.Empty:
                continue
            if message is None:
                return self._unknown(command_id, "se perdió el enlace")
            if message.get("command_id") != command_id:
                continue
            if message["op"] == "accepted":
                deadline = time.monotonic() + duration + self.result_margin_s
            elif message["op"] == "rejected":
                return AgentOutcome(command_id, "rejected", message.get("detail") or message["reason"])
            else:
                return self._result(command_id, message)

    def _result(self, command_id: str, message: dict) -> AgentOutcome:
        status, reason = message["status"], message.get("reason")
        commanded = message.get("commanded_us") or {}
        if status == "failed":
            return self._unknown(command_id, f"fallo del backend: {reason}")
        if status == "stopped" and reason != "operator_stop":
            self.blocked = f"el agente detuvo {command_id}: {reason}"
        return AgentOutcome(command_id, status, reason or "", commanded)
