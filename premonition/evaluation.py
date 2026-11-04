"""Evaluación A2/A3 sobre ejecuciones grabadas, con denominadores explícitos.

Ambos métodos juzgan los mismos fotogramas. Detección (por ensayo) y recuperación (por ejecución)
se informan por separado: las ejecuciones se grabaron con un solo método de decisión.
"""
import hashlib
import json
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .models import Cell, Contract, Verdict
from .perception import decode_image, measure_scene, frame_issues, scene_issues
from .evidence import EvidenceChanged, contract_unchanged, verified_frame, verified_plan
from .verifier import judge_a2, judge_a3, thresholds_sha256

INDEPENDENT_ANNOTATORS = {"sim_world", "operator"}
SYNTHETIC_WARNING = ("Datos sintéticos: comprueban que el flujo de evaluación funciona; no son evidencia "
                     "del desempeño físico ni del aporte de la referencia generada.")


class ThresholdsChanged(RuntimeError):
    pass


@dataclass(frozen=True)
class Trial:
    run_id: str
    contract_id: str
    role: str
    truth: str
    failure_class: str | None
    has_reference: bool
    a2: Verdict
    a3: Verdict


def _load_run(path: Path) -> tuple[dict, list[dict], dict]:
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    verified_plan(manifest)
    events = [json.loads(line) for line in (path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    labels_file = path / "labels.json"
    labels = json.loads(labels_file.read_text(encoding="utf-8")) if labels_file.exists() else {}
    return manifest, events, labels


def _frozen_before_action(contract: Contract, events: list[dict]) -> bool:
    frozen = [e["seq"] for e in events
              if e["event"] == "contract_frozen" and e["contract_id"] == contract.contract_id]
    sent = [e["seq"] for e in events if e["event"] == "command_sent"
            and (e["step_id"], e["attempt"]) == (contract.step_id, contract.attempt)]
    return bool(frozen) and bool(sent) and max(frozen) < min(sent)


def _trial_or_reason(path: Path, contract: Contract, events: list[dict], labels: dict, cell: Cell):
    if contract.thresholds_sha256 != thresholds_sha256(cell) or not contract_unchanged(contract, events):
        return "contract_changed"
    label = labels.get(contract.contract_id)
    if label is None:
        return "no_label"
    if label["annotator"] not in INDEPENDENT_ANNOTATORS:
        return "label_not_independent"
    observation = next((e for e in events if e["event"] == "observation"
                        and e["contract_id"] == contract.contract_id), None)
    if observation is None:
        return "no_valid_observation"
    reference = None
    if contract.role == "post":
        if not _frozen_before_action(contract, events):
            return "not_frozen_before_action"
        if contract.reference_sha256:
            try:
                reference = (path / "references" / f"{contract.contract_id}.jpg").read_bytes()
            except OSError:
                return "reference_missing"
            if hashlib.sha256(reference).hexdigest() != contract.reference_sha256:
                return "reference_changed"
    try:
        jpeg = verified_frame(path, observation)
    except EvidenceChanged as error:
        return str(error)
    if frame_issues(jpeg, cell.perception):
        return "invalid_frame"
    image = decode_image(jpeg)
    if scene_issues(image, cell):
        return "region_out_of_frame"
    a2 = judge_a2(contract, measure_scene(image, cell), cell.perception)
    a3, _ = judge_a3(a2, contract, jpeg, reference, cell)
    return Trial(path.name, contract.contract_id, contract.role, label["truth"], label["class"],
                 reference is not None, a2, a3)


def collect_trials(runs: list[Path], cell: Cell) -> tuple[list[Trial], list[dict]]:
    expected = thresholds_sha256(cell)
    trials, excluded = [], []
    for path in map(Path, runs):
        manifest, events, labels = _load_run(path)
        if manifest.get("replay_of"):
            continue
        if manifest["thresholds_sha256"] != expected:
            raise ThresholdsChanged(f"{path.name} se grabó con otros umbrales; los umbrales deben estar congelados")
        for contract_file in sorted((path / "contracts").glob("*.json")):
            contract = Contract.model_validate_json(contract_file.read_text(encoding="utf-8"))
            if contract.role == "pre":
                continue
            outcome = _trial_or_reason(path, contract, events, labels, cell)
            if isinstance(outcome, Trial):
                trials.append(outcome)
            else:
                excluded.append({"run": path.name, "contract": contract.contract_id, "reason": outcome})
    return trials, excluded


def _ratio(num: int, den: int) -> dict:
    return {"num": num, "den": den}


def _method_metrics(trials: list[Trial], method: str) -> dict:
    verdicts = [(t.truth, getattr(t, method).outcome) for t in trials]
    failed = [outcome for truth, outcome in verdicts if truth == "failed"]
    correct = [outcome for truth, outcome in verdicts if truth == "correct"]
    accepted = failed.count("pass")
    acceptances = accepted + correct.count("pass")
    return {"trials": len(verdicts),
            "failures_accepted": _ratio(accepted, len(failed)),
            "correct_rejected": _ratio(correct.count("fail"), len(correct)),
            "abstentions": _ratio(sum(1 for _, outcome in verdicts if outcome == "unknown"), len(verdicts)),
            "acceptances": acceptances,
            "failures_accepted_share_of_acceptances": _ratio(accepted, acceptances)}


def _recovery(loaded: list[tuple[dict, list[dict]]]) -> dict:
    tally: dict[str, list[int]] = {}
    for _, events in loaded:
        decisions = [e for e in events if e["event"] == "decision" and e["phase"] == "post"]
        failures = {(e["step_id"], e["failure_class"]) for e in decisions if e["verdict"] == "fail"}
        for step_id, failure_class in sorted(failures):
            recovered = any(e["step_id"] == step_id and e["verdict"] == "pass" for e in decisions)
            entry = tally.setdefault(failure_class, [0, 0])
            entry[0] += int(recovered)
            entry[1] += 1
    return {name: _ratio(*values) for name, values in sorted(tally.items())}


def assign_splits(run_ids: list[str], seed: str = "premonition-splits-1") -> dict[str, str]:
    """Reparte corridas completas, nunca fotogramas sueltos, de forma estable."""
    names = ("development", "development", "calibration", "evaluation")
    return {run_id: names[int(hashlib.sha256(f"{seed}:{run_id}".encode()).hexdigest(), 16) % len(names)]
            for run_id in sorted(run_ids)}


def evaluate(runs: list[Path], cell: Cell, split: str | None = None) -> dict:
    paths = [Path(run) for run in runs]
    if split:
        chosen = assign_splits([p.name for p in paths])
        paths = [p for p in paths if chosen[p.name] == split]
    trials, excluded = collect_trials(paths, cell)
    loaded = [_load_run(p)[:2] for p in paths]
    originals = [(m, e) for m, e in loaded if not m.get("replay_of")]
    latencies = [e["latency_ms"] for _, events in originals for e in events if e["event"] == "reference_generated"]
    commands = sum(1 for _, events in originals for e in events if e["event"] == "command_sent")
    synthetic = sum(1 for m, _ in originals if m["synthetic"])
    return {"provenance": {"synthetic_runs": synthetic, "real_runs": len(originals) - synthetic},
            "warning": SYNTHETIC_WARNING if synthetic else None,
            "composition": {
                "scenarios": dict(sorted(Counter(m["scenario"] for m, _ in originals).items())),
                "failure_classes": dict(sorted(Counter(t.failure_class for t in trials if t.failure_class).items())),
                "trials_with_reference": sum(1 for t in trials if t.has_reference)},
            "methods": {"A2": _method_metrics(trials, "a2"), "A3": _method_metrics(trials, "a3")},
            "kits": {"completed": sum(1 for m, _ in originals if m["status"] == "completed"),
                     "attempted": len(originals)},
            "recovery": _recovery(originals),
            "cost": {"commands_per_run": round(commands / len(originals), 2) if originals else None,
                     "reference_latency_ms_median": statistics.median(latencies) if latencies else None,
                     "api_usd": round(sum(e.get("usd", 0) for _, events in originals for e in events
                                          if e["event"] == "api_usage"), 6)},
            "excluded": excluded}
