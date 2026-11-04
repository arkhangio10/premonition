"""Mundo sintético: escena dibujada por código y fallos inyectados. Nada aquí observa hardware."""
import hashlib
import threading
from dataclasses import dataclass, field

import cv2
import numpy as np

from .models import CaptureRequest, Cell, Contract, Frame, MotionCommand, MotionResult

WIDTH, HEIGHT = 960, 540
PIECE_SIZE = 80
PIECE_BGR = {"A": (40, 40, 210), "B": (60, 180, 60), "C": (210, 70, 40)}
GRIPPER_BGR = (40, 40, 42)
BANNER = "SYNTHETIC TEST DATA"


@dataclass(frozen=True)
class Scenario:
    name: str
    title: str
    description: str
    missing: tuple[str, ...] = ()
    grasp_failures: dict[str, int] = field(default_factory=dict)
    swap_on_pick: tuple[str, str] | None = None
    misplace: tuple[str, tuple[int, int]] | None = None
    drop: str | None = None
    occlude: tuple[str, str, str, int] | None = None
    lost_ack: tuple[str, str] | None = None


SCENARIOS = {s.name: s for s in [
    Scenario("success", "Kit completo", "Las tres piezas llegan a su compartimento."),
    Scenario("grasp_failed", "Agarre fallido", "El primer agarre de B no levanta la pieza; el reintento funciona.",
             grasp_failures={"B": 1}),
    Scenario("grasp_failed_persistent", "Agarre fallido persistente",
             "Ningún agarre de B levanta la pieza; se agota el límite de intentos.", grasp_failures={"B": 99}),
    Scenario("wrong_piece", "Pieza equivocada",
             "Alguien intercambia B y C justo después de la comprobación previa; llega C al centro.",
             swap_on_pick=("B", "C")),
    Scenario("missing_piece", "Pieza ausente", "C no está en su origen al inspeccionar la escena.", missing=("C",)),
    Scenario("misplaced", "Pieza mal colocada", "B queda en el compartimento correcto pero fuera de tolerancia.",
             misplace=("B", (50, 0))),
    Scenario("dropped", "Pieza perdida", "B cae después del agarre y no llega al destino.", drop="B"),
    Scenario("occluded_once", "Oclusión temporal", "La pinza tapa el destino en la primera observación.",
             occlude=("place", "B", "center", 1)),
    Scenario("occluded_persistent", "Oclusión persistente", "La pinza tapa el destino en todas las observaciones.",
             occlude=("place", "B", "center", 99)),
    Scenario("lost_ack", "Confirmación perdida", "No llega el resultado de la orden de agarre de B.",
             lost_ack=("pick", "B")),
]}
REQUIRED_REPLAYS = ("success", "grasp_failed", "wrong_piece", "missing_piece")


def _rect(region, offset=(0, 0)):
    cx = region.x + region.w // 2 + offset[0]
    cy = region.y + region.h // 2 + offset[1]
    half = PIECE_SIZE // 2
    return (cx - half, cy - half), (cx + half, cy + half)


class SimWorld:
    def __init__(self, scenario: Scenario, cell: Cell):
        self.scenario, self.cell = scenario, cell
        self.positions = {p.id: (p.source_id, (0, 0)) for p in cell.pieces if p.id not in scenario.missing}
        self.held = None
        self.grasp_failures = dict(scenario.grasp_failures)
        self.occlusions = scenario.occlude[3] if scenario.occlude else 0
        self.last_command = None
        self.truth: dict[str, dict] = {}

    def put(self, piece_id, location_id, offset=(0, 0)):
        self.positions[piece_id] = (location_id, offset)

    def remove(self, piece_id):
        self.positions.pop(piece_id, None)

    def piece_at(self, location_id):
        return next((p for p, (where, _) in self.positions.items() if where == location_id), None)

    def render(self, seq: int, occlude_region: str | None = None) -> bytes:
        image = np.full((HEIGHT, WIDTH, 3), self.cell.perception.background_bgr, np.uint8)
        for location in self.cell.locations:
            box = location.region
            cv2.rectangle(image, (box.x, box.y), (box.x + box.w, box.y + box.h), (170, 174, 176), 1)
        for piece_id, (where, offset) in self.positions.items():
            top_left, bottom_right = _rect(self.cell.location(where).region, offset)
            cv2.rectangle(image, top_left, bottom_right, PIECE_BGR[piece_id], -1)
        if occlude_region:
            box = self.cell.location(occlude_region).region
            cx, cy = box.x + box.w // 2, box.y + box.h // 2
            cv2.rectangle(image, (cx - 30, 0), (cx + 30, cy), GRIPPER_BGR, -1)
        noise = np.random.default_rng(seq).normal(0, 2.0, image.shape)
        image = np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)
        cv2.putText(image, BANNER, (12, HEIGHT - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (70, 70, 200), 2, cv2.LINE_AA)
        return cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()

    def apply(self, command: MotionCommand):
        """Registra la verdad del mundo, independiente de lo que concluya el verificador."""
        self.last_command = command
        key = f"{command.step_id}#{command.attempt}"
        if command.action == "pick":
            self.truth[key] = self._pick(command)
        else:
            self.truth[key] = self._place(command)

    def _pick(self, command):
        piece, source = command.piece_id, command.location_id
        if self.scenario.swap_on_pick and self.scenario.swap_on_pick[0] == piece:
            other = self.scenario.swap_on_pick[1]
            self.positions[piece], self.positions[other] = self.positions[other], self.positions[piece]
        if self.grasp_failures.get(piece, 0) > 0:
            self.grasp_failures[piece] -= 1
            return {"truth": "failed", "class": "grasp_failed"}
        actual = self.piece_at(source)
        self.remove(actual)
        self.held = None if self.scenario.drop == piece else actual
        if self.scenario.drop == piece:
            return {"truth": "failed", "class": "piece_lost"}
        return {"truth": "correct", "class": None} if actual == piece else {"truth": "failed", "class": "wrong_piece"}

    def _place(self, command):
        piece, destination = command.piece_id, command.location_id
        held, self.held = self.held, None
        if held is None:
            return {"truth": "failed", "class": "piece_lost"}
        misplaced = self.scenario.misplace and self.scenario.misplace[0] == piece
        self.put(held, destination, self.scenario.misplace[1] if misplaced else (0, 0))
        if held != piece:
            return {"truth": "failed", "class": "wrong_piece"}
        return {"truth": "failed", "class": "misplaced"} if misplaced else {"truth": "correct", "class": None}


class SimMotion:
    """Aplica órdenes al mundo sintético. No existe ruta desde aquí hacia I²C ni hacia la Jetson."""

    kind = "simulado"

    def __init__(self, world: SimWorld, delay_s: float = 0.0):
        self.world, self.delay_s = world, delay_s
        self.cancelled = threading.Event()

    def execute(self, command: MotionCommand) -> MotionResult:
        if self.cancelled.wait(self.delay_s):
            return MotionResult(command_id=command.command_id, status="stopped", detail="orden simulada cancelada")
        lost = self.world.scenario.lost_ack
        if lost and (command.action, command.piece_id) == lost:
            return MotionResult(command_id=command.command_id, status="unknown",
                                detail="sin resultado de la orden dentro del plazo")
        self.world.apply(command)
        return MotionResult(command_id=command.command_id, status="completed",
                            detail="orden simulada terminada; esto no prueba el resultado físico")

    def cancel(self):
        self.cancelled.set()
        return "orden simulada cancelada"


class SimCamera:
    kind = "sintética"

    def __init__(self, world: SimWorld):
        self.world = world
        self.seq = 0

    def _occluded_region(self, request: CaptureRequest) -> str | None:
        rule = self.world.scenario.occlude
        last = self.world.last_command
        if not rule or not last or request.phase != "post" or self.world.occlusions <= 0:
            return None
        if (last.action, last.piece_id) != (rule[0], rule[1]) or last.step_id != request.step_id:
            return None
        self.world.occlusions -= 1
        return rule[2]

    def capture(self, request: CaptureRequest) -> Frame:
        self.seq += 1
        jpeg = self.world.render(self.seq, self._occluded_region(request))
        return Frame(frame_id=f"f{self.seq:04d}", run_id=request.run_id, step_id=request.step_id,
                     attempt=request.attempt, phase=request.phase, command_id=request.command_id,
                     token=request.token, source="synthetic", jpeg=jpeg,
                     sha256=hashlib.sha256(jpeg).hexdigest())


def simulated_reference(initial_jpeg: bytes, contract: Contract, cell: Cell) -> bytes:
    """Fixture de referencia: dibuja el contrato sobre la foto inicial. No es salida de Muse Image."""
    image = cv2.imdecode(np.frombuffer(initial_jpeg, np.uint8), cv2.IMREAD_COLOR)
    for predicate in contract.predicates:
        box = cell.location(predicate.region).region
        if predicate.kind == "region_empty":
            image[box.y + 1:box.y + box.h - 1, box.x + 1:box.x + box.w - 1] = cell.perception.background_bgr
        else:
            image[box.y + 1:box.y + box.h - 1, box.x + 1:box.x + box.w - 1] = cell.perception.background_bgr
            cv2.rectangle(image, *_rect(box), PIECE_BGR[predicate.piece], -1)
    return cv2.imencode(".jpg", cv2.GaussianBlur(image, (3, 3), 0), [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()
