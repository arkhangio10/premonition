"""Enlace de solo lectura con la Jetson por OpenSSH nativo.

Los scripts viajan por stdin: nada se instala en la Jetson y ningún comando nombra los programas
de servos. Este módulo no contiene órdenes de movimiento.
"""
import base64
import hashlib
import json
import re
import subprocess
import time
import uuid
from pathlib import Path

from .models import CaptureRequest, Frame
from .perception import decode_image, quality_metrics

SSH_EXE = r"C:\Windows\System32\OpenSSH\ssh.exe"
AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"


class CameraError(RuntimeError):
    pass


class JetsonError(RuntimeError):
    pass


def ssh_argv(host: str, remote_command: str) -> list[str]:
    return [SSH_EXE, "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=7", host, remote_command]


def _script(name: str) -> bytes:
    return (AGENT_DIR / name).read_bytes().replace(b"\r\n", b"\n")


def _stderr_tail(completed) -> str:
    return completed.stderr.decode("utf-8", "replace").strip()[-300:]


class JetsonCamera:
    kind = "jetson"

    def __init__(self, host: str, run=None):
        self.host, self.run = host, run or subprocess.run

    def capture(self, request: CaptureRequest) -> Frame:
        if not re.fullmatch(r"[0-9a-f]{32}", request.token):
            raise CameraError("token de captura inválido")
        completed = self.run(ssh_argv(self.host, f"python3 - --token {request.token}"),
                             input=_script("capture_once.py"), capture_output=True, timeout=45)
        output = completed.stdout.decode("utf-8", "replace").strip().splitlines()
        try:
            reply = json.loads(output[-1])
        except (IndexError, ValueError):
            raise CameraError(f"sin respuesta de la cámara: {_stderr_tail(completed)}") from None
        if completed.returncode != 0 or not reply.get("ok"):
            raise CameraError(reply.get("error") or _stderr_tail(completed))
        jpeg = base64.b64decode(reply["jpeg_b64"])
        return Frame(frame_id=f"jetson-{reply['token'][:8]}", run_id=request.run_id, step_id=request.step_id,
                     attempt=request.attempt, phase=request.phase, command_id=request.command_id,
                     token=reply["token"], source="jetson", jpeg=jpeg, sha256=hashlib.sha256(jpeg).hexdigest())


def check_connection(host: str, run=None) -> dict:
    started = time.perf_counter()
    try:
        completed = (run or subprocess.run)(ssh_argv(host, "hostname"), capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        return {"connected": False, "detail": "sin respuesta en 15 s"}
    if completed.returncode != 0:
        return {"connected": False, "detail": _stderr_tail(completed)}
    return {"connected": True, "hostname": completed.stdout.decode().strip(),
            "latency_ms": round((time.perf_counter() - started) * 1000)}


def read_commanded_pulses(host: str, run=None) -> dict:
    """Lee pulsos comandados sin escribir registros. No mide la posición física."""
    completed = (run or subprocess.run)(ssh_argv(host, "python3 -"), input=_script("read_registers.py"),
                                        capture_output=True, timeout=20)
    if completed.returncode != 0:
        raise JetsonError(f"no se pudieron leer los registros: {_stderr_tail(completed)}")
    return json.loads(completed.stdout.decode("utf-8"))


def inspect_system(host: str, run=None) -> dict:
    """Lee inventario y analiza constantes por AST; nunca inicia los programas encontrados."""
    completed = (run or subprocess.run)(ssh_argv(host, "python3 -"), input=_script("inspect_system.py"),
                                        capture_output=True, timeout=20)
    if completed.returncode != 0:
        raise JetsonError(f"no se pudo inspeccionar la Jetson: {_stderr_tail(completed)}")
    return json.loads(completed.stdout.decode("utf-8"))


def check_agent_syntax(host: str, run=None) -> dict:
    """Compila los scripts con el intérprete de la Jetson sin ejecutar su main ni dejar archivos."""
    checker = "python3 -c 'import sys; compile(sys.stdin.buffer.read(), \"agent\", \"exec\"); print(sys.version.split()[0])'"
    results = {}
    for name in ("premonition_agent.py", "capture_once.py", "read_registers.py", "inspect_system.py"):
        completed = (run or subprocess.run)(ssh_argv(host, checker), input=_script(name), capture_output=True, timeout=20)
        results[name] = (completed.stdout.decode().strip() if completed.returncode == 0
                         else f"ERROR: {_stderr_tail(completed)}")
    return results


def capture_to_disk(host: str, root: Path) -> dict:
    """Foto real con el control motriz sin iniciar. La calidad se mide; el umbral real sigue sin calibrar."""
    token = uuid.uuid4().hex
    request = CaptureRequest(run_id="camera-check", step_id="camera", attempt=1, phase="inspect",
                             command_id=None, token=token)
    frame = JetsonCamera(host).capture(request)
    if frame.token != token:
        raise CameraError("el token devuelto no corresponde a esta captura")
    image = decode_image(frame.jpeg)
    if image is None:
        raise CameraError("la cámara devolvió una imagen que no se puede decodificar")
    folder = Path(root) / "real" / "captures"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{token[:8]}.jpg"
    (folder / name).write_bytes(frame.jpeg)
    return {"file": name, "width": image.shape[1], "height": image.shape[0], "sha256": frame.sha256,
            "quality": quality_metrics(image), "source": frame.source,
            "note": "Foto real sin calibrar: encuadre, exposición y regiones siguen pendientes."}
