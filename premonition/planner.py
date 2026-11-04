"""Planificadores: construcción determinista del kit y fixture local claramente etiquetado."""
import re

from .models import Cell, InspectScene, Pick, Place, Plan, StopStep, VerifyStep
from .validator import PlanRejected


def build_kit_plan(assignments: dict[str, str], cell: Cell) -> Plan:
    steps = [InspectScene(step_id="s1", action="inspect_scene", scope="initial")]

    def add(step_type, **fields):
        steps.append(step_type(step_id=f"s{len(steps) + 1}", **fields))
        return steps[-1].step_id

    for piece_id, destination_id in assignments.items():
        spec = cell.piece(piece_id)
        if spec is None:
            raise PlanRejected([f"pieza desconocida {piece_id!r}"])
        picked = add(Pick, action="pick", piece_id=piece_id, source_id=spec.source_id)
        add(VerifyStep, action="verify_step", target_step_id=picked)
        dropped = add(Place, action="place", piece_id=piece_id, destination_id=destination_id)
        add(VerifyStep, action="verify_step", target_step_id=dropped)
    add(InspectScene, action="inspect_scene", scope="final")
    add(StopStep, action="stop", reason="kit_terminado")
    return Plan(steps=steps)


def request_assignments(request_text: str, cell: Cell) -> dict[str, str]:
    """Objetivo independiente del plan: cada pieza debe tener un destino explícito único."""
    destinations = {l.label.casefold(): l.id for l in cell.locations if l.kind == "destination"}
    destinations.update({l.id.casefold(): l.id for l in cell.locations if l.kind == "destination"})
    pieces = {p.id.casefold(): p.id for p in cell.pieces}
    alternatives = "|".join(map(re.escape, destinations))
    piece_pattern = "|".join(map(re.escape, pieces))
    found = re.findall(rf"\b({piece_pattern})\b[^,;.]*?\b({alternatives})\b", request_text, re.IGNORECASE)
    assignments = {pieces[p.casefold()]: destinations[d.casefold()] for p, d in found}
    if len(found) != len(pieces) or set(assignments) != set(pieces.values()):
        raise PlanRejected([
            "Especifica una vez cada pieza y su destino, o proporciona assignments explícitas. "
            "El planificador local no interpreta peticiones libres; MODEL_API_KEY habilita Meta."])
    if len(set(assignments.values())) != len(assignments):
        raise PlanRejected(["cada pieza necesita un destino diferente"])
    return assignments


class FixturePlanner:
    """Sustituye a Muse Spark en simulación. No es inferencia: solo reconoce el patrón del ejemplo."""

    source = "fixture_simulado"

    def plan(self, request_text: str, cell: Cell) -> Plan:
        return build_kit_plan(request_assignments(request_text, cell), cell)
