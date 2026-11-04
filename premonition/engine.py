"""Máquina de estados: anticipar, actuar, observar y decidir.

Cada paso congela contrato y referencia antes de ordenar el movimiento. Tras la acción solo una
observación fresca puede hacer avanzar el plan; un ACK o una orden terminada nunca lo hacen.
"""
import hashlib
import json
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from .evidence import RunStore
from .models import (Cell, CaptureRequest, Contract, InspectScene, Limits, Mode, MotionCommand, Pick, Place,
                     Plan, Predicate, RegionMeasure, Verdict, VerifyStep)
from .motion import MotionDisabled
from .perception import check_frame, decode_image, discrete_facts, frame_issues, measure_scene, quality_metrics, scene_issues
from .verifier import VERIFIER_VERSION, judge_a2, judge_a3, thresholds_sha256
from .validator import PlanRejected, validate_plan

RETRYABLE = {"grasp_failed"}
STOP_TEXT = {
    "operator_stop": "Parada de software solicitada por el operador.",
    "motion_disabled": "El movimiento físico está deshabilitado.",
    "motion_unknown": "No se pudo determinar el resultado del movimiento; reconcilia la escena antes de seguir.",
    "motion_rejected": "El controlador rechazó la orden.",
    "motion_stopped": "El movimiento se detuvo antes de terminar.",
    "unknown_state": "No hay una observación válida; no se declara éxito.",
    "missing_piece": "Falta una pieza necesaria; repón la pieza y reinicia.",
    "wrong_piece": "Hay una pieza distinta a la requerida; corrige la escena y reinicia.",
    "misplaced": "La pieza está fuera de la tolerancia del compartimento; corrige la escena y reinicia.",
    "piece_lost": "La pieza no llegó al destino y se desconoce dónde está.",
    "grasp_failed": "El agarre falló y se agotó el límite de intentos.",
    "precondition_failed": "Una precondición observada no se cumple.",
    "ambiguous_state": "La escena no coincide con ningún resultado esperado.",
    "kit_incomplete": "La inspección final no confirma el kit.",
}


@dataclass
class EngineConfig:
    mode: Mode
    reference: Callable[[bytes, Contract, Cell], bytes] | None
    reference_source: str = "fixture_simulado"
    decision_method: str = "A2"
    planner_source: str = "fixture_simulado"
    request_text: str = ""
    scenario: str | None = None
    replay_of: str | None = None
    expected_assignments: dict[str, str] | None = None


@dataclass
class RunResult:
    status: str
    failure_class: str | None
    stop_reason: str
    state: dict
    store: RunStore


@dataclass
class _Halt:
    failure_class: str
    detail: str = ""


def next_action(verdict: Verdict, attempt: int, reobservations: int, limits: Limits) -> str:
    if verdict.outcome == "pass":
        return "continue"
    if verdict.outcome == "unknown":
        return "reobserve" if reobservations < limits.max_reobserve else "stop"
    if verdict.failure_class in RETRYABLE and attempt < limits.max_attempts:
        return "retry"
    return "stop"


class Engine:
    def __init__(self, cell: Cell, plan: Plan, motion, camera, store: RunStore, config: EngineConfig):
        issues = validate_plan(plan, cell, config.expected_assignments)
        if issues:
            raise PlanRejected(issues)
        self.cell, self.plan, self.motion, self.camera, self.store = cell, plan, motion, camera, store
        self.config = config
        self.plan_sha256 = hashlib.sha256(plan.model_dump_json().encode()).hexdigest()
        self.thresholds = thresholds_sha256(cell)
        self.attempts: dict[str, int] = defaultdict(lambda: 1)
        self.post_contracts: dict[str, Contract] = {}
        self.command_ids: dict[str, str] = {}
        self.references: dict[str, bytes | None] = {}
        self.reference_cache: dict[str, tuple[bytes, str]] = {}
        self.seen_frames: set[str] = set()
        self.frame_counter = 0
        self._stop = threading.Event()
        self._stop_detail = ""
        self.final_verified = False
        placed = [s for s in plan.steps if isinstance(s, Place)]
        self.state = {"requested": {s.piece_id: s.destination_id for s in placed},
                      "commanded": [], "observed": {}, "uncertainty": []}

    def request_stop(self, detail: str):
        self._stop_detail = detail
        self._stop.set()
        return self.motion.cancel()

    def run(self) -> RunResult:
        self.store.write_manifest(
            scenario=self.config.scenario, cell_id=self.cell.cell_id, plan=self.plan.model_dump(),
            plan_sha256=self.plan_sha256, thresholds_sha256=self.thresholds, verifier_version=VERIFIER_VERSION,
            planner_source=self.config.planner_source, reference_source=self.config.reference_source,
            decision_method=self.config.decision_method, request_text=self.config.request_text,
            motion=self.motion.kind, camera=self.camera.kind, replay_of=self.config.replay_of, status="running",
            expected_assignments=self.config.expected_assignments, cell_config=self.cell.model_dump(mode="json"))
        self.store.log("run_started", motion=self.motion.kind, camera=self.camera.kind)
        index = 0
        positions = {step.step_id: i for i, step in enumerate(self.plan.steps)}
        while True:
            step = self.plan.steps[index]
            if self._stop.is_set():
                return self._finish("stopped", "operator_stop", self._stop_detail)
            self.store.log("step_started", step_id=step.step_id, action=step.action,
                           attempt=self.attempts[getattr(step, "target_step_id", step.step_id)])
            if step.action == "stop":
                if not self.final_verified:
                    return self._finish("stopped", "kit_incomplete", "Falta una inspección final aprobada.")
                return self._finish("completed", None, step.reason)
            outcome = self._handle(step)
            if isinstance(outcome, _Halt):
                return self._finish("stopped", outcome.failure_class, outcome.detail)
            index = positions[outcome] if isinstance(outcome, str) else index + 1

    def _handle(self, step):
        if isinstance(step, InspectScene):
            return self._inspect(step)
        if isinstance(step, VerifyStep):
            return self._verify(step)
        return self._act(step)

    def _finish(self, status: str, failure_class: str | None, detail: str) -> RunResult:
        reason = detail or STOP_TEXT.get(failure_class, "")
        self.store.log("run_finished", status=status, failure_class=failure_class, stop_reason=reason)
        self.store.write_manifest(status=status, failure_class=failure_class, stop_reason=reason, state=self.state)
        return RunResult(status, failure_class, reason, self.state, self.store)

    def _contract(self, step_id: str, attempt: int, action: str, role: str, piece_id: str | None,
                  predicates: list[Predicate], **fields) -> Contract:
        contract = Contract(contract_id=f"{step_id}-{attempt}-{role}", run_id=self.store.run_id, step_id=step_id,
                            attempt=attempt, plan_sha256=self.plan_sha256, action=action, role=role,
                            piece_id=piece_id, predicates=predicates, thresholds_sha256=self.thresholds,
                            **({"initial_frame_sha256": None, "reference_sha256": None,
                                "reference_source": None} | fields))
        self.store.save_contract(contract)
        return contract

    def _inspect(self, step: InspectScene):
        actions = [s for s in self.plan.steps if isinstance(s, (Pick, Place))]
        if step.scope == "initial":
            predicates = [Predicate(kind="piece_present", region=s.source_id, piece=s.piece_id)
                          for s in actions if isinstance(s, Pick)]
            predicates += [Predicate(kind="region_empty", region=s.destination_id)
                           for s in actions if isinstance(s, Place)]
        else:
            predicates = [Predicate(kind="piece_present", region=s.destination_id, piece=s.piece_id)
                          for s in actions if isinstance(s, Place)]
        role = "inspect" if step.scope == "initial" else "final"
        contract = self._contract(step.step_id, 1, step.action, role, None, predicates)
        _, verdict, decision, _ = self._observe(contract, "inspect", None)
        if step.scope == "final" and decision == "continue":
            self.final_verified = True
        return None if decision == "continue" else self._halt(verdict)

    def _halt(self, verdict: Verdict) -> _Halt:
        return _Halt(verdict.failure_class or "unknown_state")

    def _act(self, step: Pick | Place):
        attempt = self.attempts[step.step_id]
        piece, location = step.piece_id, step.source_id if isinstance(step, Pick) else step.destination_id
        before = (Predicate(kind="piece_present", region=location, piece=piece) if isinstance(step, Pick)
                  else Predicate(kind="region_empty", region=location))
        after = (Predicate(kind="region_empty", region=location) if isinstance(step, Pick)
                 else Predicate(kind="piece_present", region=location, piece=piece))
        pre = self._contract(step.step_id, attempt, step.action, "pre", piece, [before])
        frame, verdict, decision, measures = self._observe(pre, "pre", None)
        if decision != "continue":
            return self._halt(verdict)
        post = self._freeze(step, attempt, piece, after, frame, measures)
        self.post_contracts[step.step_id] = post
        command = MotionCommand(command_id=uuid.uuid4().hex, run_id=self.store.run_id, step_id=step.step_id,
                                attempt=attempt, action=step.action, piece_id=piece, location_id=location)
        self.command_ids[step.step_id] = command.command_id
        return self._command(command)

    def _freeze(self, step, attempt, piece, predicate, frame, measures) -> Contract:
        """Fija contrato y referencia antes de actuar; se reutiliza solo con iguales precondiciones."""
        facts = discrete_facts(measures, self.cell.perception)
        key = hashlib.sha256(json.dumps([step.step_id, facts], sort_keys=True).encode()).hexdigest()
        reference, source, error = None, None, None
        reused = key in self.reference_cache
        if reused:
            reference, source = self.reference_cache[key]
        elif self.config.reference is not None:
            draft = self._contract(step.step_id, attempt, step.action, "post", piece, [predicate],
                                   initial_frame_sha256=frame.sha256)
            started = time.perf_counter()
            try:
                reference = self.config.reference(frame.jpeg, draft, self.cell)
                source = self.config.reference_source
                self.reference_cache[key] = (reference, source)
                self.store.log("reference_generated", step_id=step.step_id, attempt=attempt, source=source,
                               latency_ms=round((time.perf_counter() - started) * 1000, 1))
            except Exception as failure:
                error = str(failure)
                self.store.log("reference_failed", step_id=step.step_id, attempt=attempt, error=error)
        digest = hashlib.sha256(reference).hexdigest() if reference else None
        contract = self._contract(step.step_id, attempt, step.action, "post", piece, [predicate],
                                  initial_frame_sha256=frame.sha256, reference_sha256=digest,
                                  reference_source=source)
        path = self.store.save_reference(contract.contract_id, reference) if reference else None
        self.references[contract.contract_id] = reference
        self.store.log("contract_frozen", step_id=step.step_id, attempt=attempt, contract_id=contract.contract_id,
                       predicates=[p.model_dump() for p in contract.predicates], reference_sha256=digest,
                       reference_source=source, reference_reused=reused, reference_path=path,
                       precondition_key=key)
        return contract

    def _command(self, command: MotionCommand):
        if self._stop.is_set():
            return _Halt("operator_stop", self._stop_detail)
        record = {"command_id": command.command_id, "step_id": command.step_id, "attempt": command.attempt,
                  "action": command.action, "piece_id": command.piece_id, "location_id": command.location_id,
                  "status": "sent"}
        self.state["commanded"].append(record)
        self.store.log("command_sent", **record)
        try:
            result = self.motion.execute(command)
        except MotionDisabled as blocked:
            record["status"] = "blocked"
            return _Halt("motion_disabled", str(blocked))
        record["status"] = result.status
        self.store.log("motion_result", step_id=command.step_id, attempt=command.attempt, **result.model_dump())
        if result.status == "completed":
            return None
        if self._stop.is_set():
            return _Halt("operator_stop", self._stop_detail)
        return _Halt({"unknown": "motion_unknown", "rejected": "motion_rejected"}.get(result.status, "motion_stopped"),
                     f"{STOP_TEXT.get('motion_' + result.status, '')} {result.detail}".strip())

    def _verify(self, step: VerifyStep):
        target = step.target_step_id
        post = self.post_contracts[target]
        _, verdict, decision, _ = self._observe(post, "post", self.command_ids[target])
        if decision == "continue":
            if post.action == "pick":
                self.state["uncertainty"].append(
                    f"{post.piece_id}: el origen quedó vacío, pero la pieza en la pinza no se mide directamente")
            return None
        if decision == "retry":
            self.attempts[target] += 1
            return target
        return self._halt(verdict)

    def _sleep_for_settling(self, phase: str):
        if phase == "post" and self.cell.limits.settle_s:
            time.sleep(self.cell.limits.settle_s)

    def _observe(self, contract: Contract, phase: str, command_id: str | None):
        """Toma observaciones frescas hasta tener pass/fail o agotar el límite de abstenciones."""
        reobservations = 0
        while True:
            self._sleep_for_settling(phase)
            frame, verdict, measures = self._capture_and_judge(contract, phase, command_id)
            decision = next_action(verdict, contract.attempt, reobservations, self.cell.limits)
            self.store.log("decision", step_id=contract.step_id, attempt=contract.attempt, phase=phase,
                           contract_id=contract.contract_id, verdict=verdict.outcome,
                           failure_class=verdict.failure_class, reasons=verdict.reasons, next=decision,
                           method=self.config.decision_method)
            if verdict.outcome != "pass":
                self.state["uncertainty"] += [f"{contract.step_id} intento {contract.attempt}: {r}"
                                              for r in verdict.reasons]
            if decision != "reobserve":
                return frame, verdict, decision, measures
            reobservations += 1

    def _capture_and_judge(self, contract: Contract, phase: str, command_id: str | None):
        request = CaptureRequest(run_id=self.store.run_id, step_id=contract.step_id, attempt=contract.attempt,
                                 phase=phase, command_id=command_id, token=uuid.uuid4().hex)
        try:
            frame = self.camera.capture(request)
        except Exception as failure:
            return self._rejected(request, [f"camera_error: {failure}"])
        issues = check_frame(frame, request, self.seen_frames)
        self.seen_frames.add(frame.sha256)
        if not issues:
            issues = frame_issues(frame.jpeg, self.cell.perception)
        if issues:
            return self._rejected(request, issues, frame.frame_id)
        image = decode_image(frame.jpeg)
        issues = scene_issues(image, self.cell)
        if issues:
            return self._rejected(request, issues, frame.frame_id)
        measures = measure_scene(image, self.cell)
        a2 = judge_a2(contract, measures, self.cell.perception)
        a3, similarity = judge_a3(a2, contract, frame.jpeg, self.references.get(contract.contract_id), self.cell)
        verdict = a3 if self.config.decision_method == "A3" else a2
        self.state["observed"] = discrete_facts(measures, self.cell.perception)
        path = self.store.save_frame(frame)
        self.store.log("observation", step_id=contract.step_id, attempt=contract.attempt, phase=phase,
                       contract_id=contract.contract_id, frame_id=frame.frame_id, frame_path=path,
                       frame_sha256=frame.sha256, command_id=command_id, verdict=verdict.outcome,
                       a2=a2.model_dump(), a3=a3.model_dump(), similarity=similarity,
                       quality=quality_metrics(image), source=frame.source, observed=self.state["observed"],
                       measures={k: _measure_view(m) for k, m in measures.items()})
        return frame, verdict, measures

    def _rejected(self, request: CaptureRequest, issues: list[str], frame_id: str | None = None):
        self.store.log("frame_rejected", step_id=request.step_id, attempt=request.attempt, phase=request.phase,
                       frame_id=frame_id, issues=issues)
        return None, Verdict(outcome="unknown", reasons=[f"frame_rejected:{i}" for i in issues]), {}


def _measure_view(measure: RegionMeasure) -> dict:
    return {key: round(value, 3) if isinstance(value, float) else value
            for key, value in measure.model_dump().items() if key != "region"}
