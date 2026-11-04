"""Carga de la celda y lista exacta de lo que falta antes de cualquier movimiento físico."""
from pathlib import Path
import math

from .models import Cell, Route

JOINTS = {"base", "shoulder", "elbow", "wrist_pitch", "wrist_roll", "gripper"}


def load_cell(path: str | Path) -> Cell:
    return Cell.model_validate_json(Path(path).read_text(encoding="utf-8"))


def required_routes(cell: Cell) -> list[str]:
    routes = [f"pick:{p.source_id}" for p in cell.pieces]
    routes += [f"place:{l.id}" for l in cell.locations if l.kind == "destination"]
    return routes


def _route_gaps(cell: Cell, route_id: str, route: Route) -> list[str]:
    gaps = []
    if not route.validated_by_operator:
        gaps.append(f"ruta {route_id}: sin validar por el operador")
    if not route.waypoints:
        gaps.append(f"ruta {route_id}: no contiene puntos")
    previous = cell.observe_pose.targets_us if cell.observe_pose is not None else None
    if previous is not None and set(previous) != set(cell.joints):
        previous = None
    for point in route.waypoints:
        label = f"ruta {route_id}, punto {point.name}"
        if point.targets_us is None or point.duration_s is None:
            gaps.append(f"{label}: sin pulsos o duración")
            previous = None
            continue
        if not math.isfinite(point.duration_s) or not 0 < point.duration_s <= 10:
            gaps.append(f"{label}: duración fuera de (0, 10] s")
            previous = None
            continue
        if set(point.targets_us) != set(cell.joints):
            gaps.append(f"{label}: debe nombrar exactamente las seis articulaciones")
            previous = None
            continue
        for joint, value in point.targets_us.items():
            if joint not in cell.envelope_us:
                gaps.append(f"{label}: falta envolvente de {joint}")
                continue
            low, high = cell.envelope_us[joint]
            if not low <= value <= high:
                gaps.append(f"{label}: {joint}={value} µs fuera de la envolvente [{low}, {high}]")
            if previous and abs(value - previous[joint]) / point.duration_s > cell.max_speed_us_s:
                gaps.append(f"{label}: {joint} supera la velocidad de {cell.max_speed_us_s} µs/s")
        previous = point.targets_us
    return gaps


def hardware_gaps(cell: Cell) -> list[str]:
    """Devuelve cada dato físico ausente; vacío no habilita movimiento por sí solo."""
    gaps = []
    if set(cell.joints) != JOINTS or len(cell.joints) != len(JOINTS):
        gaps.append("articulaciones: deben ser exactamente las seis del agente")
    if set(cell.envelope_us) != set(cell.joints):
        gaps.append("envolvente: debe definir exactamente las articulaciones configuradas")
    for joint, (low, high) in cell.envelope_us.items():
        if low >= high:
            gaps.append(f"envolvente {joint}: mínimo debe ser menor que máximo")
    if cell.synthetic:
        gaps.append("la celda es sintética y no describe hardware real")
    if not cell.stop_procedure_confirmed:
        gaps.append("parada física: procedimiento sin confirmar por el operador")
    if not cell.pieces:
        gaps.append("piezas: ninguna definida")
    if not cell.locations:
        gaps.append("ubicaciones: ninguna definida (orígenes y compartimentos de la bandeja)")
    if cell.perception is None:
        gaps.append("percepción: umbrales sin calibrar con la escena real")
    if cell.observe_pose is None or cell.observe_pose.targets_us is None:
        gaps.append("pose de observación: sin enseñar")
    else:
        gaps += _route_gaps(cell, "observación", Route(
            waypoints=[cell.observe_pose], validated_by_operator=True))
    if len({p.id for p in cell.pieces}) != len(cell.pieces):
        gaps.append("piezas: IDs repetidos")
    if len({l.id for l in cell.locations}) != len(cell.locations):
        gaps.append("ubicaciones: IDs repetidos")
    for piece in cell.pieces:
        source = cell.location(piece.source_id)
        if source is None or source.kind != "source":
            gaps.append(f"pieza {piece.id}: origen no definido como source")
        if piece.appearance is None:
            gaps.append(f"pieza {piece.id}: apariencia sin calibrar")
    for location in cell.locations:
        if location.region is None:
            gaps.append(f"ubicación {location.id}: región sin calibrar")
    if cell.pieces and not any(l.kind == "destination" for l in cell.locations):
        gaps.append("ubicaciones: falta un destino")
    for route_id in required_routes(cell):
        if route_id not in cell.routes:
            gaps.append(f"ruta {route_id}: sin enseñar")
    for route_id, route in cell.routes.items():
        gaps += _route_gaps(cell, route_id, route)
    return gaps
