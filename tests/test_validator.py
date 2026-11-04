import json

import pytest

from premonition.cell import hardware_gaps
from premonition.models import Route, Waypoint
from premonition.validator import PlanRejected, parse_plan, plan_json_schema, validate_plan


def steps_of(plan):
    return [step.model_dump() for step in plan.steps]


def rejected_issues(raw):
    with pytest.raises(PlanRejected) as caught:
        parse_plan(raw)
    return caught.value.issues


def test_demo_plan_is_valid(demo_plan, sim_cell):
    assert validate_plan(demo_plan, sim_cell) == []


@pytest.mark.parametrize("goal", [
    "Place A on the left, B in the center, and C on the right.",
    "Place part A left, part B center, part C right.",
])
def test_english_goals_keep_the_requested_destinations(goal, sim_cell):
    from premonition.planner import FixturePlanner, request_assignments

    expected = {"A": "left", "B": "center", "C": "right"}
    assert request_assignments(goal, sim_cell) == expected
    assert validate_plan(FixturePlanner().plan(goal, sim_cell), sim_cell, expected) == []


def test_demo_plan_survives_json_round_trip(demo_plan, sim_cell):
    assert parse_plan(demo_plan.model_dump_json()) == demo_plan


def test_rejects_malformed_json():
    assert rejected_issues("{not json")


@pytest.mark.parametrize("step", [
    {"step_id": "s1", "action": "run_python", "code": "import smbus"},
    {"step_id": "s1", "action": "shell", "command": "python3 servo_test.py"},
    {"step_id": "s1", "action": "i2c_write", "address": 64},
    {"step_id": "s1", "action": "move_joint", "targets": {"gripper": 1500}},
])
def test_rejects_actions_outside_the_allow_list(step):
    assert rejected_issues({"steps": [step]})


def test_rejects_extra_field_on_a_step():
    step = {"step_id": "s1", "action": "pick", "piece_id": "A", "source_id": "src_a", "pulse_us": 1500}
    assert rejected_issues({"steps": [step]})


def test_model_output_cannot_carry_an_enable_flag(demo_plan):
    raw = json.loads(demo_plan.model_dump_json())
    raw["motion_enabled"] = True
    assert rejected_issues(raw)


def test_rejects_unknown_piece(demo_plan, sim_cell):
    raw = steps_of(demo_plan)
    raw[1]["piece_id"] = "A; rm -rf /"
    assert any("pieza desconocida" in i for i in validate_plan(parse_plan({"steps": raw}), sim_cell))


def test_rejects_source_that_does_not_match_the_piece(demo_plan, sim_cell):
    raw = steps_of(demo_plan)
    raw[1]["source_id"] = "src_b"
    assert any("origen" in i for i in validate_plan(parse_plan({"steps": raw}), sim_cell))


def test_rejects_place_without_a_verified_pick(sim_cell):
    plan = parse_plan({"steps": [
        {"step_id": "s1", "action": "inspect_scene", "scope": "initial"},
        {"step_id": "s2", "action": "place", "piece_id": "A", "destination_id": "left"},
    ]})
    assert any("no sostiene" in i for i in validate_plan(plan, sim_cell))


def test_rejects_action_without_verification_before_the_next_action(sim_cell):
    plan = parse_plan({"steps": [
        {"step_id": "s1", "action": "inspect_scene", "scope": "initial"},
        {"step_id": "s2", "action": "pick", "piece_id": "A", "source_id": "src_a"},
        {"step_id": "s3", "action": "place", "piece_id": "A", "destination_id": "left"},
    ]})
    assert any("sin verificar" in i for i in validate_plan(plan, sim_cell))


def test_rejects_second_pick_while_holding(sim_cell):
    plan = parse_plan({"steps": [
        {"step_id": "s1", "action": "inspect_scene", "scope": "initial"},
        {"step_id": "s2", "action": "pick", "piece_id": "A", "source_id": "src_a"},
        {"step_id": "s3", "action": "verify_step", "target_step_id": "s2"},
        {"step_id": "s4", "action": "pick", "piece_id": "B", "source_id": "src_b"},
    ]})
    assert any("ya sostiene" in i for i in validate_plan(plan, sim_cell))


def test_rejects_two_pieces_on_one_destination(sim_cell):
    raw = []
    for n, (piece, source) in enumerate((("A", "src_a"), ("B", "src_b"))):
        base = n * 4 + 2
        raw += [
            {"step_id": f"s{base}", "action": "pick", "piece_id": piece, "source_id": source},
            {"step_id": f"s{base + 1}", "action": "verify_step", "target_step_id": f"s{base}"},
            {"step_id": f"s{base + 2}", "action": "place", "piece_id": piece, "destination_id": "left"},
            {"step_id": f"s{base + 3}", "action": "verify_step", "target_step_id": f"s{base + 2}"},
        ]
    plan = parse_plan({"steps": [{"step_id": "s1", "action": "inspect_scene", "scope": "initial"}] + raw})
    assert any("ocupado" in i for i in validate_plan(plan, sim_cell))


def test_rejects_verify_of_a_step_that_is_not_the_pending_action(demo_plan, sim_cell):
    raw = steps_of(demo_plan)
    raw[2]["target_step_id"] = "s1"
    assert any("sin verificar" in i or "verify_step" in i
               for i in validate_plan(parse_plan({"steps": raw}), sim_cell))


def test_rejects_plan_longer_than_the_limit(demo_plan, sim_cell):
    filler = [{"step_id": f"x{n}", "action": "inspect_scene", "scope": "initial"} for n in range(40)]
    assert any("límite" in i for i in validate_plan(parse_plan({"steps": filler}), sim_cell))


def test_rejects_repeated_step_ids(demo_plan, sim_cell):
    raw = steps_of(demo_plan)
    raw[2]["step_id"] = raw[1]["step_id"]
    assert any("repetido" in i for i in validate_plan(parse_plan({"steps": raw}), sim_cell))


def test_rejects_plan_without_final_inspection(demo_plan, sim_cell):
    raw = [s for s in steps_of(demo_plan) if s.get("scope") != "final"]
    assert any("inspección final" in i for i in validate_plan(parse_plan({"steps": raw}), sim_cell))


def test_rejects_plan_that_stops_holding_a_piece(sim_cell):
    plan = parse_plan({"steps": [
        {"step_id": "s1", "action": "inspect_scene", "scope": "initial"},
        {"step_id": "s2", "action": "pick", "piece_id": "A", "source_id": "src_a"},
        {"step_id": "s3", "action": "verify_step", "target_step_id": "s2"},
        {"step_id": "s4", "action": "inspect_scene", "scope": "final"},
        {"step_id": "s5", "action": "stop", "reason": "fin"},
    ]})
    assert any("sostiene" in i for i in validate_plan(plan, sim_cell))


def test_expected_assignments_must_match_the_plan(demo_plan, sim_cell):
    issues = validate_plan(demo_plan, sim_cell, expected={"A": "right", "B": "center", "C": "left"})
    assert any("asignación" in i for i in issues)


def test_schema_stays_inside_the_documented_strict_subset():
    def walk(node):
        if isinstance(node, dict):
            assert "oneOf" not in node and "allOf" not in node
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    schema = plan_json_schema()
    assert "anyOf" not in schema
    walk(schema)


def test_incomplete_real_cell_reports_every_missing_physical_datum(real_cell):
    incomplete = real_cell.model_copy(update={"stop_procedure_confirmed": False, "observe_pose": None,
                                              "pieces": [], "locations": [], "perception": None, "routes": {}})
    gaps = hardware_gaps(incomplete)
    joined = " | ".join(gaps)
    for expected in ("piezas", "ubicaciones", "pose de observación", "percepción", "parada física"):
        assert expected in joined


def test_synthetic_cell_can_never_satisfy_the_hardware_gate(sim_cell):
    assert any("sintética" in gap for gap in hardware_gaps(sim_cell))


def _route(sim_cell, **overrides):
    targets = {joint: 1500 for joint in sim_cell.joints}
    targets.update(overrides)
    return Route(waypoints=[Waypoint(name="approach", targets_us=targets, duration_s=2.0)],
                 validated_by_operator=True)


def test_route_outside_the_envelope_is_a_gap(sim_cell):
    cell = sim_cell.model_copy(update={"routes": {"pick:src_a": _route(sim_cell, gripper=2500)}})
    assert any("fuera de la envolvente" in gap for gap in hardware_gaps(cell))


def test_route_without_pulses_is_a_gap(sim_cell):
    route = Route(waypoints=[Waypoint(name="approach", targets_us=None, duration_s=None)],
                  validated_by_operator=True)
    cell = sim_cell.model_copy(update={"routes": {"pick:src_a": route}})
    assert any("sin pulsos" in gap for gap in hardware_gaps(cell))


def test_route_not_validated_by_the_operator_is_a_gap(sim_cell):
    route = _route(sim_cell).model_copy(update={"validated_by_operator": False})
    cell = sim_cell.model_copy(update={"routes": {"pick:src_a": route}})
    assert any("operador" in gap for gap in hardware_gaps(cell))


def test_route_faster_than_the_speed_cap_is_a_gap(sim_cell):
    first = {joint: 1000 for joint in sim_cell.joints}
    second = dict(first, base=2000)
    route = Route(waypoints=[Waypoint(name="a", targets_us=first, duration_s=2.0),
                             Waypoint(name="b", targets_us=second, duration_s=0.5)],
                  validated_by_operator=True)
    cell = sim_cell.model_copy(update={"routes": {"pick:src_a": route}})
    assert any("velocidad" in gap for gap in hardware_gaps(cell))
