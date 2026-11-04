"""Validador determinista del plan. El modelo propone; este módulo decide si es ejecutable."""
import copy
import json

from pydantic import ValidationError

from .models import Cell, InspectScene, Pick, Place, Plan, StopStep, VerifyStep


class PlanRejected(Exception):
    def __init__(self, issues: list[str]):
        super().__init__("; ".join(issues))
        self.issues = issues


def parse_plan(raw: str | dict) -> Plan:
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return Plan.model_validate(data)
    except ValueError as error:
        details = error.errors() if isinstance(error, ValidationError) else []
        issues = [f"{'.'.join(map(str, d['loc']))}: {d['msg']}" for d in details]
        raise PlanRejected(issues or [f"JSON inválido: {error}"]) from error


def _strict_subset(node):
    """Quita oneOf/discriminator: el modo strict documentado solo admite anyOf bajo la raíz."""
    if isinstance(node, dict):
        node.pop("discriminator", None)
        node.pop("title", None)
        if "oneOf" in node:
            node["anyOf"] = node.pop("oneOf")
        if "properties" in node:
            node["properties"] = {key: _strict_subset(value) for key, value in node["properties"].items()}
            node["required"] = sorted(node["properties"])
        for key, value in node.items():
            if key != "properties":
                node[key] = _strict_subset(value)
    elif isinstance(node, list):
        return [_strict_subset(value) for value in node]
    return node


def plan_json_schema() -> dict:
    return _strict_subset(copy.deepcopy(Plan.model_json_schema()))


def validate_plan(plan: Plan, cell: Cell, expected: dict[str, str] | None = None) -> list[str]:
    """Simula el plan simbólicamente y devuelve todos los motivos de rechazo."""
    issues = []
    steps = plan.steps
    if len(steps) > cell.limits.max_plan_steps:
        issues.append(f"el plan tiene {len(steps)} pasos; el límite es {cell.limits.max_plan_steps}")
    ids = [step.step_id for step in steps]
    issues += [f"step_id repetido: {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    if not steps or not (isinstance(steps[0], InspectScene) and steps[0].scope == "initial"):
        issues.append("el plan debe empezar con inspect_scene inicial")
    if not steps or not isinstance(steps[-1], StopStep):
        issues.append("el plan debe terminar con stop")
    if not any(isinstance(s, InspectScene) and s.scope == "final" for s in steps):
        issues.append("falta la inspección final del kit")
    if sum(isinstance(s, StopStep) for s in steps) != 1:
        issues.append("debe existir un único stop, al final del plan")
    if any(isinstance(s, StopStep) for s in steps[:-1]):
        issues.append("stop no puede aparecer antes del final")
    inspections = [(i, s.scope) for i, s in enumerate(steps) if isinstance(s, InspectScene)]
    if inspections != [(0, "initial"), (len(steps) - 2, "final")]:
        issues.append("solo se permiten la inspección inicial y la final inmediatamente antes de stop")

    held, pending, moved = None, None, set()
    placed: dict[str, str] = {}
    for step in steps:
        where = f"{step.step_id} ({step.action})"
        if isinstance(step, VerifyStep):
            if pending is None or step.target_step_id != pending:
                issues.append(f"{where}: verify_step debe apuntar a la acción sin verificar")
            pending = None
            continue
        if pending is not None:
            issues.append(f"{where}: la acción {pending} sigue sin verificar")
            pending = None
        if isinstance(step, Pick):
            piece = cell.piece(step.piece_id)
            if piece is None:
                issues.append(f"{where}: pieza desconocida {step.piece_id!r}")
            elif piece.source_id != step.source_id:
                issues.append(f"{where}: el origen de {step.piece_id} es {piece.source_id}")
            if held is not None:
                issues.append(f"{where}: la pinza ya sostiene {held}")
            if step.piece_id in moved:
                issues.append(f"{where}: {step.piece_id} ya se recogió")
            held = step.piece_id
            moved.add(step.piece_id)
            pending = step.step_id
        elif isinstance(step, Place):
            location = cell.location(step.destination_id)
            if location is None or location.kind != "destination":
                issues.append(f"{where}: destino desconocido {step.destination_id!r}")
            if held != step.piece_id:
                issues.append(f"{where}: la pinza no sostiene {step.piece_id}")
            if step.destination_id in placed.values():
                issues.append(f"{where}: el destino {step.destination_id} ya está ocupado")
            placed[step.piece_id] = step.destination_id
            held = None
            pending = step.step_id
        elif isinstance(step, StopStep) and held is not None:
            issues.append(f"{where}: el plan termina y la pinza sostiene {held}")
    if pending is not None:
        issues.append(f"la acción {pending} queda sin verificar")
    if expected is not None and placed != expected:
        issues.append(f"la asignación del plan {placed} no coincide con la solicitada {expected}")
    if expected is None and set(placed) != {p.id for p in cell.pieces}:
        issues.append("el plan debe colocar todas las piezas del kit")
    return issues
