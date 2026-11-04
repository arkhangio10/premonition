"""Ejecuta escenarios sintéticos y reproduce ejecuciones grabadas sin ningún transporte."""
import hashlib
import json
import uuid
from pathlib import Path

from .engine import Engine, EngineConfig, RunResult
from .evidence import EvidenceChanged, RunStore, contract_unchanged, new_run_id, verified_frame, verified_plan
from .models import Cell, Contract, Frame, Mode, MotionResult, Plan
from .sim import SCENARIOS, Scenario, SimCamera, SimMotion, SimWorld, simulated_reference
from .verifier import thresholds_sha256

FIXTURE_VERSION = "synthetic-2-en"


def _labels(world: SimWorld, store: RunStore) -> dict:
    """Etiquetas tomadas del mundo sintético, nunca de la salida del verificador."""
    labels = {}
    for path in sorted((store.path / "contracts").glob("*.json")):
        contract = Contract.model_validate_json(path.read_text(encoding="utf-8"))
        if contract.role == "pre":
            continue
        if contract.role == "post":
            truth = world.truth.get(f"{contract.step_id}#{contract.attempt}")
        elif contract.role == "inspect":
            truth = ({"truth": "failed", "class": "missing_piece"} if world.scenario.missing
                     else {"truth": "correct", "class": None})
        else:
            ok = all(world.piece_at(p.region) == p.piece and world.positions[p.piece][1] == (0, 0)
                     for p in contract.predicates)
            truth = {"truth": "correct", "class": None} if ok else {"truth": "failed", "class": "kit_incomplete"}
        if truth:
            labels[contract.contract_id] = {**truth, "annotator": "sim_world"}
    return labels


def run_scenario(scenario: Scenario, cell: Cell, plan: Plan, root, reference=simulated_reference, world=None,
                 motion=None, request_text: str = "", planner_source: str = "fixture_simulado",
                 reference_source: str = "fixture_simulado", run_id: str | None = None,
                 store: RunStore | None = None, on_engine=None, decision_method: str = "A2",
                 expected_assignments: dict[str, str] | None = None) -> RunResult:
    world = world or SimWorld(scenario, cell)
    store = store or RunStore(root, run_id or new_run_id(scenario.name), Mode.SIMULATION, synthetic=True)
    config = EngineConfig(mode=Mode.SIMULATION, reference=reference, scenario=scenario.name,
                          request_text=request_text, planner_source=planner_source,
                          reference_source=reference_source, decision_method=decision_method,
                          expected_assignments=expected_assignments)
    engine = Engine(cell, plan, motion or SimMotion(world), SimCamera(world), store, config)
    if on_engine:
        on_engine(engine)
    result = engine.run()
    store.save_labels(_labels(world, store))
    return result


class ReplayMotion:
    """Devuelve los resultados grabados. No actúa sobre nada."""

    kind = "replay"

    def __init__(self, recorded: list[dict]):
        self.recorded = {(e["step_id"], e["attempt"]): e for e in recorded}

    def execute(self, command) -> MotionResult:
        entry = self.recorded[(command.step_id, command.attempt)]
        return MotionResult(command_id=command.command_id, status=entry["status"], detail=entry["detail"])

    def cancel(self):
        return "replay: sin movimiento que cancelar"


class ReplayCamera:
    """Sirve los fotogramas grabados en orden, sellados con la correlación de la nueva ejecución."""

    kind = "replay"

    def __init__(self, source: Path, observations: list[dict]):
        self.source = source
        self.pending: dict[tuple, list[dict]] = {}
        for entry in observations:
            self.pending.setdefault((entry["step_id"], entry["attempt"], entry["phase"]), []).append(entry)

    def capture(self, request) -> Frame:
        queue = self.pending.get((request.step_id, request.attempt, request.phase))
        if not queue:
            raise LookupError(f"el registro no contiene más fotogramas para {request.step_id}")
        entry = queue.pop(0)
        jpeg = verified_frame(self.source, entry)
        return Frame(frame_id=entry["frame_id"], run_id=request.run_id, step_id=request.step_id,
                     attempt=request.attempt, phase=request.phase, command_id=request.command_id,
                     token=request.token, source="replay", jpeg=jpeg, sha256=hashlib.sha256(jpeg).hexdigest())


def replay_run(source: str | Path, cell: Cell, root, store: RunStore | None = None, on_engine=None) -> RunResult:
    source = Path(source)
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    plan = verified_plan(manifest)
    if manifest["thresholds_sha256"] != thresholds_sha256(cell):
        raise EvidenceChanged("La calibración o versión del verificador difiere de la grabación.")
    events = [json.loads(line) for line in (source / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    frozen = {(e["step_id"], e["attempt"]): e for e in events if e["event"] == "contract_frozen"}
    for contract_file in (source / "contracts").glob("*.json"):
        contract = Contract.model_validate_json(contract_file.read_text(encoding="utf-8"))
        if not contract_unchanged(contract, events):
            raise EvidenceChanged(f"contract_changed:{contract.contract_id}")
        if contract.reference_sha256:
            reference = (source / "references" / f"{contract.contract_id}.jpg").read_bytes()
            if hashlib.sha256(reference).hexdigest() != contract.reference_sha256:
                raise EvidenceChanged(f"reference_changed:{contract.contract_id}")

    def recorded_reference(initial_jpeg, contract, _cell):
        original = Contract.model_validate_json(
            (source / "contracts" / f"{contract.contract_id}.json").read_text(encoding="utf-8"))
        if not original.reference_sha256:
            return None
        return (source / "references" / f"{contract.contract_id}.jpg").read_bytes()

    store = store or RunStore(root, new_run_id(f"replay-{manifest['scenario']}"), Mode.REPLAY,
                              synthetic=manifest["synthetic"])
    config = EngineConfig(mode=Mode.REPLAY, reference=recorded_reference, reference_source=manifest["reference_source"],
                          scenario=manifest["scenario"], request_text=manifest["request_text"],
                          planner_source=manifest["planner_source"], replay_of=manifest["run_id"],
                          decision_method=manifest.get("decision_method", "A2"),
                          expected_assignments=manifest.get("expected_assignments"))
    motion = ReplayMotion([e for e in events if e["event"] == "motion_result"])
    camera = ReplayCamera(source, [e for e in events if e["event"] == "observation"])
    engine = Engine(cell, plan, motion, camera, store, config)
    if on_engine:
        on_engine(engine)
    return engine.run()


def fixture_path(root, name: str) -> Path:
    return Path(root) / "fixtures" / "synthetic" / f"fixture-{name}"


def record_fixture(root, name: str, cell: Cell, plan: Plan) -> Path:
    """Graba el escenario sintético una vez; lo regraba si cambiaron los umbrales de la celda."""
    path = fixture_path(root, name)
    manifest = path / "manifest.json"
    if manifest.exists():
        recorded = json.loads(manifest.read_text(encoding="utf-8"))
        plan_hash = hashlib.sha256(plan.model_dump_json().encode()).hexdigest()
        if (recorded["thresholds_sha256"] == thresholds_sha256(cell)
                and recorded.get("plan_sha256") == plan_hash and recorded["status"] != "running"
                and recorded.get("fixture_version") == FIXTURE_VERSION):
            return path
        # Conservar la evidencia anterior cuando cambia la calibración o el plan.
        archive = Path(root) / "fixtures" / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        path.rename(archive / f"{path.name}-{uuid.uuid4().hex[:8]}")
    result = run_scenario(SCENARIOS[name], cell, plan, Path(root) / "fixtures", run_id=f"fixture-{name}")
    result.store.write_manifest(fixture_version=FIXTURE_VERSION)
    return path
