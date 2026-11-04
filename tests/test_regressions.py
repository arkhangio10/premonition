"""Regresiones de la auditoría: éxito, exclusión, costes y evidencia. Sin hardware ni API real."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from premonition.cell import hardware_gaps, required_routes
from premonition.engine import Engine, EngineConfig
from premonition.evaluation import collect_trials
from premonition.evidence import RunStore, EvidenceChanged
from premonition.meta import Budget, BudgetExceeded, MetaClient
from premonition.models import Mode, Plan, Route, StopStep, Waypoint
from premonition.planner import FixturePlanner, build_kit_plan
from premonition.scenarios import run_scenario, replay_run
from premonition.sim import SCENARIOS, SimCamera, SimMotion, SimWorld
from premonition.validator import PlanRejected, validate_plan
from premonition.verifier import thresholds_sha256
from premonition.web import create_app, DEFAULT_REQUEST


def wait_finished(client, run_id):
    for _ in range(300):
        view = client.get(f"/api/runs/{run_id}").json()
        if view["status"] != "running":
            return view
        time.sleep(0.02)
    raise AssertionError("la ejecución no terminó")


def test_early_stop_is_rejected_by_validator_and_engine(sim_cell, demo_plan, tmp_path):
    plan = Plan(steps=[demo_plan.steps[0], StopStep(step_id="early", action="stop", reason="fin")]
                + demo_plan.steps[1:])
    assert any("stop" in issue for issue in validate_plan(plan, sim_cell))
    world = SimWorld(SCENARIOS["success"], sim_cell)
    with pytest.raises(PlanRejected):
        Engine(sim_cell, plan, SimMotion(world), SimCamera(world),
               RunStore(tmp_path, "early", Mode.SIMULATION, True),
               EngineConfig(mode=Mode.SIMULATION, reference=None))
    assert world.last_command is None


def test_partial_kit_cannot_be_accepted_by_default(sim_cell):
    assert validate_plan(build_kit_plan({"A": "left"}, sim_cell), sim_cell)


@pytest.mark.parametrize("assignments", [
    {"A": "left"}, {"A": "right", "B": "center", "C": "left"},
])
def test_api_rejects_incomplete_or_wrong_planner_goal(assignments, sim_cell, tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setattr(FixturePlanner, "plan", lambda *args: build_kit_plan(assignments, sim_cell))
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        response = client.post("/api/runs", json={"scenario": "success", "mode": "simulation",
                                                 "request_text": DEFAULT_REQUEST})
        assert response.status_code == 422
        assert client.get("/api/runs").json() == []


def test_concurrent_start_is_rejected_while_planner_is_pending(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    entered, release = threading.Event(), threading.Event()
    original = FixturePlanner.plan

    def delayed(self, *args):
        entered.set()
        assert release.wait(5)
        return original(self, *args)

    monkeypatch.setattr(FixturePlanner, "plan", delayed)
    body = {"scenario": "success", "mode": "simulation", "request_text": DEFAULT_REQUEST}
    with TestClient(create_app(tmp_path, pace_s=0), base_url="http://127.0.0.1") as client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(client.post, "/api/runs", json=body)
            try:
                assert entered.wait(5)
                assert client.post("/api/runs", json=body).status_code == 409
                assert client.post("/api/evaluation").status_code == 409
            finally:
                release.set()
            response = first.result(5)
        assert response.status_code == 200
        assert wait_finished(client, response.json()["run_id"])["status"] == "completed"


def physical_cell(sim_cell):
    return sim_cell.model_copy(update={
        "synthetic": False, "stop_procedure_confirmed": True,
        "observe_pose": Waypoint(name="observe", targets_us={j: 1500 for j in sim_cell.joints}, duration_s=2.0),
        "routes": {key: Route(waypoints=[], validated_by_operator=True) for key in required_routes(sim_cell)},
    })


def test_empty_operator_approved_routes_remain_blocked(sim_cell):
    gaps = hardware_gaps(physical_cell(sim_cell))
    assert sum("no contiene puntos" in gap for gap in gaps) == 6


@pytest.mark.parametrize("duration", [0.0, -1.0, float("nan"), 11.0])
def test_invalid_route_duration_never_divides_or_passes(sim_cell, duration):
    cell = physical_cell(sim_cell)
    point = cell.observe_pose.model_copy(update={"duration_s": duration})
    cell = cell.model_copy(update={"routes": {"pick:src_a": Route(
        waypoints=[point], validated_by_operator=True)}})
    assert any("duración" in gap for gap in hardware_gaps(cell))


def test_observation_pose_is_checked_against_envelope(sim_cell):
    cell = physical_cell(sim_cell)
    pose = cell.observe_pose.model_copy(update={"targets_us": {j: 9000 for j in cell.joints}})
    assert any("observación" in gap and "fuera de la envolvente" in gap
               for gap in hardware_gaps(cell.model_copy(update={"observe_pose": pose})))


def test_pending_api_reservations_count_against_the_limit():
    budget = Budget(10, 0.01)
    reservation = budget.reserve(0.01)
    with pytest.raises(BudgetExceeded):
        budget.reserve(0.001)
    budget.settle(reservation, 0.002)
    budget.reserve(0.007)


def test_chat_cannot_bypass_tiny_budget_with_zero_estimate():
    calls = []
    http = httpx.Client(base_url="https://audit.invalid", transport=httpx.MockTransport(
        lambda request: calls.append(request)))
    client = MetaClient("fake", Budget(10, 0.000001), http=http)
    with pytest.raises(BudgetExceeded):
        client.chat_json("test", "test", {}, "Test")
    assert calls == []


def test_ambiguous_network_failure_keeps_a_conservative_charge():
    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)

    from premonition.meta import MetaError
    budget = Budget(10, 0.01)
    client = MetaClient("fake", budget, http=httpx.Client(base_url="https://audit.invalid",
                        transport=httpx.MockTransport(timeout)))
    with pytest.raises(MetaError):
        client.edit_image(b"x", "test")
    assert budget.usd == 0.01
    with pytest.raises(BudgetExceeded):
        client.edit_image(b"x", "test")


def test_changed_recorded_frame_is_excluded_and_replay_stops(sim_cell, demo_plan, tmp_path):
    result = run_scenario(SCENARIOS["success"], sim_cell, demo_plan, tmp_path)
    event = next(e for e in result.store.events if e["event"] == "observation" and e["phase"] == "post")
    (result.store.path / event["frame_path"]).write_bytes(SimWorld(SCENARIOS["success"], sim_cell).render(123))
    trials, excluded = collect_trials([result.store.path], sim_cell)
    assert any(e["reason"] == "frame_changed" for e in excluded)
    assert event["contract_id"] not in {t.contract_id for t in trials}
    replayed = replay_run(result.store.path, sim_cell, tmp_path / "replay")
    assert replayed.status == "stopped" and replayed.failure_class == "unknown_state"


def test_changed_contract_is_excluded_and_replay_refused(sim_cell, demo_plan, tmp_path):
    result = run_scenario(SCENARIOS["success"], sim_cell, demo_plan, tmp_path)
    path = result.store.path / "contracts" / "s2-1-post.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["predicates"] = []
    path.write_text(json.dumps(data), encoding="utf-8")
    _, excluded = collect_trials([result.store.path], sim_cell)
    assert any(e["reason"] == "contract_changed" for e in excluded)
    with pytest.raises(EvidenceChanged, match="contract_changed"):
        replay_run(result.store.path, sim_cell, tmp_path / "replay")


@pytest.mark.parametrize("field", ["appearance", "region", "limits"])
def test_full_calibration_is_part_of_recording_hash(sim_cell, field):
    if field == "appearance":
        look = sim_cell.pieces[0].appearance.model_copy(update={"hue": 90.0})
        piece = sim_cell.pieces[0].model_copy(update={"appearance": look})
        changed = sim_cell.model_copy(update={"pieces": [piece] + sim_cell.pieces[1:]})
    elif field == "region":
        box = sim_cell.locations[0].region.model_copy(update={"x": 125})
        location = sim_cell.locations[0].model_copy(update={"region": box})
        changed = sim_cell.model_copy(update={"locations": [location] + sim_cell.locations[1:]})
    else:
        changed = sim_cell.model_copy(update={"limits": sim_cell.limits.model_copy(update={"max_attempts": 1})})
    assert thresholds_sha256(changed) != thresholds_sha256(sim_cell)


def test_a3_selection_reaches_engine(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with TestClient(create_app(tmp_path, pace_s=0), base_url="http://127.0.0.1") as client:
        response = client.post("/api/runs", json={"scenario": "success", "mode": "simulation",
                                                 "request_text": DEFAULT_REQUEST, "decision_method": "A3"})
        assert response.status_code == 200
        view = wait_finished(client, response.json()["run_id"])
        assert view["decision_method"] == "A3" and view["status"] == "completed"
