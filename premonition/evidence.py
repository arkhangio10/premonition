"""Evidencia por ejecución. Sintético y real viven en carpetas separadas."""
import json
import hashlib
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import Contract, Frame, Mode, Plan


class EvidenceChanged(ValueError):
    pass


def verified_plan(manifest: dict) -> Plan:
    plan = Plan.model_validate(manifest["plan"])
    if hashlib.sha256(plan.model_dump_json().encode()).hexdigest() != manifest.get("plan_sha256"):
        raise EvidenceChanged("plan_changed")
    return plan


def verified_frame(path: Path, entry: dict) -> bytes:
    base = (path / "frames").resolve()
    target = (path / entry["frame_path"]).resolve()
    if not target.is_relative_to(base):
        raise EvidenceChanged("frame_path_outside_run")
    try:
        jpeg = target.read_bytes()
    except OSError as error:
        raise EvidenceChanged("frame_missing") from error
    if hashlib.sha256(jpeg).hexdigest() != entry.get("frame_sha256"):
        raise EvidenceChanged("frame_changed")
    return jpeg


def contract_unchanged(contract: Contract, events: list[dict]) -> bool:
    saved = [e for e in events if e["event"] == "contract_saved"
             and e["contract_id"] == contract.contract_id]
    digest = hashlib.sha256(contract.model_dump_json().encode()).hexdigest()
    return bool(saved) and saved[-1]["sha256"] == digest


def new_run_id(label: str) -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{label}-{uuid.uuid4().hex[:6]}"


class RunStore:
    def __init__(self, root: str | Path, run_id: str, mode: Mode, synthetic: bool):
        self.run_id, self.mode, self.synthetic = run_id, mode, synthetic
        self.path = Path(root) / ("synthetic" if synthetic else "real") / run_id
        for folder in ("frames", "references", "contracts"):
            (self.path / folder).mkdir(parents=True, exist_ok=True)
        self.events: list[dict] = []
        self._lock = threading.Lock()
        self.manifest: dict = {}

    def log(self, event: str, **fields) -> dict:
        with self._lock:
            entry = {"seq": len(self.events) + 1, "event": event, "run_id": self.run_id,
                     "mode": self.mode.value, "synthetic": self.synthetic,
                     "at": datetime.now(timezone.utc).isoformat(), **fields}
            self.events.append(entry)
            with (self.path / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def write_manifest(self, **fields):
        with self._lock:
            self.manifest.update(fields, mode=self.mode.value, synthetic=self.synthetic, run_id=self.run_id)
            (self.path / "manifest.json").write_text(
                json.dumps(self.manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_frame(self, frame: Frame) -> str:
        relative = f"frames/{frame.frame_id}.jpg"
        (self.path / relative).write_bytes(frame.jpeg)
        return relative

    def save_reference(self, contract_id: str, jpeg: bytes) -> str:
        relative = f"references/{contract_id}.jpg"
        (self.path / relative).write_bytes(jpeg)
        return relative

    def save_contract(self, contract: Contract):
        (self.path / "contracts" / f"{contract.contract_id}.json").write_text(
            contract.model_dump_json(indent=2), encoding="utf-8")
        self.log("contract_saved", contract_id=contract.contract_id,
                 sha256=hashlib.sha256(contract.model_dump_json().encode()).hexdigest())

    def save_labels(self, labels: dict):
        (self.path / "labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
