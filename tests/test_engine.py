import hashlib
import json

import pytest

from premonition.engine import Engine, EngineConfig, next_action
from premonition.evidence import RunStore
from premonition.models import Mode, MotionResult, Verdict
from premonition.motion import DisabledMotion, MotionDisabled
from premonition.scenarios import run_scenario
from premonition.sim import SCENARIOS, SimCamera, SimMotion, SimWorld, simulated_reference


def run(sim_cell, plan, tmp_path, name):
    return run_scenario(SCENARIOS[name], sim_cell, plan, tmp_path)


def events(result, kind=None):
    lines = (result.store.path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(line) for line in lines]
    return [e for e in parsed if kind is None or e["event"] == kind]


def commands(result):
    return [(e["action"], e["piece_id"]) for e in events(result, "command_sent")]


def test_success_completes_the_kit(sim_cell, demo_plan, tmp_path):
    result = run(sim_cell, demo_plan, tmp_path, "success")
    assert (result.status, result.failure_class) == ("completed", None)
    assert len(commands(result)) == 6


def test_every_record_names_the_mode_and_synthetic_origin(sim_cell, demo_plan, tmp_path):
    result = run(sim_cell, demo_plan, tmp_path, "success")
    manifest = json.loads((result.store.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "simulation" and manifest["synthetic"] is True
    assert all(e["mode"] == "simulation" and e["synthetic"] is True for e in events(result))
    assert result.store.path.parent.name == "synthetic"


def test_failed_grasp_is_retried_and_recovers(sim_cell, demo_plan, tmp_path):
    result = run(sim_cell, demo_plan, tmp_path, "grasp_failed")
    assert result.status == "completed"
    assert commands(result).count(("pick", "B")) == 2
    assert [e["next"] for e in events(result, "decision") if e["failure_class"] == "grasp_failed"] == ["retry"]


def test_retry_only_happens_after_fresh_preconditions(sim_cell, demo_plan, tmp_path):
    result = run(sim_cell, demo_plan, tmp_path, "grasp_failed")
    log = events(result)
    retry = next(i for i, e in enumerate(log) if e["event"] == "decision" and e["next"] == "retry")
    second_command = next(i for i, e in enumerate(log) if i > retry and e["event"] == "command_sent")
    assert any(e["event"] == "observation" and e["phase"] == "pre" and e["verdict"] == "pass"
               for e in log[retry:second_command])


def test_persistent_failed_grasp_stops_at_the_attempt_limit(sim_cell, demo_plan, tmp_path):
    result = run(sim_cell, demo_plan, tmp_path, "grasp_failed_persistent")
    assert (result.status, result.failure_class) == ("stopped", "grasp_failed")
    assert commands(result).count(("pick", "B")) == sim_cell.limits.max_attempts


def test_wrong_piece_stops_after_placement(sim_cell, demo_plan, tmp_path):
    result = run(sim_cell, demo_plan, tmp_path, "wrong_piece")
    assert (result.status, result.failure_class) == ("stopped", "wrong_piece")
    assert ("pick", "C") not in commands(result)


def test_missing_piece_stops_before_any_command(sim_cell, demo_plan, tmp_path):
    result = run(sim_cell, demo_plan, tmp_path, "missing_piece")
    assert (result.status, result.failure_class) == ("stopped", "missing_piece")
    assert commands(result) == []


def test_misplaced_piece_stops_without_retry(sim_cell, demo_plan, tmp_path):
    result = run(sim_cell, demo_plan, tmp_path, "misplaced")
    assert (result.status, result.failure_class) == ("stopped", "misplaced")
    assert commands(result).count(("place", "B")) == 1


def test_dropped_piece_is_not_repicked(sim_cell, demo_plan, tmp_path):
    result = run(sim_cell, demo_plan, tmp_path, "dropped")
    assert (result.status, result.failure_class) == ("stopped", "piece_lost")
    assert commands(result).count(("pick", "B")) == 1


def test_temporary_occlusion_requests_a_new_observation_and_continues(sim_cell, demo_plan, tmp_path):
    result = run(sim_cell, demo_plan, tmp_path, "occluded_once")
    assert result.status == "completed"
    assert [e["next"] for e in events(result, "decision") if e["verdict"] == "unknown"] == ["reobserve"]


def test_persistent_occlusion_stops_as_unknown(sim_cell, demo_plan, tmp_path):
    result = run(sim_cell, demo_plan, tmp_path, "occluded_persistent")
    assert (result.status, result.failure_class) == ("stopped", "unknown_state")
    assert commands(result).count(("place", "B")) == 1


def test_unknown_motion_result_stops_and_never_resends(sim_cell, demo_plan, tmp_path):
    result = run(sim_cell, demo_plan, tmp_path, "lost_ack")
    assert (result.status, result.failure_class) == ("stopped", "motion_unknown")
    assert commands(result).count(("pick", "B")) == 1
    assert not any(e["phase"] == "post" and e["step_id"] == "s6" for e in events(result, "observation"))


def test_contract_and_reference_are_frozen_before_each_command(sim_cell, demo_plan, tmp_path):
    result = run(sim_cell, demo_plan, tmp_path, "success")
    log = events(result)
    for index, entry in enumerate(log):
        if entry["event"] != "command_sent":
            continue
        frozen = [e for e in log[:index] if e["event"] == "contract_frozen" and e["step_id"] == entry["step_id"]]
        assert frozen and frozen[-1]["reference_sha256"]
        contract_file = result.store.path / "contracts" / f"{frozen[-1]['contract_id']}.json"
        contract = json.loads(contract_file.read_text(encoding="utf-8"))
        reference = result.store.path / "references" / f"{frozen[-1]['contract_id']}.jpg"
        assert hashlib.sha256(reference.read_bytes()).hexdigest() == contract["reference_sha256"]


def test_reference_failure_is_visible_and_a2_continues(sim_cell, demo_plan, tmp_path):
    def broken(initial, contract, cell):
        raise RuntimeError("HTTP 503 en Muse Image")

    result = run_scenario(SCENARIOS["success"], sim_cell, demo_plan, tmp_path, reference=broken)
    assert result.status == "completed"
    failures = events(result, "reference_failed")
    assert failures and "503" in failures[0]["error"]


def test_retry_reuses_a_reference_only_for_identical_preconditions(sim_cell, demo_plan, tmp_path):
    calls = []

    def counting(initial, contract, cell):
        calls.append((contract.step_id, contract.attempt))
        return simulated_reference(initial, contract, cell)

    result = run_scenario(SCENARIOS["grasp_failed"], sim_cell, demo_plan, tmp_path, reference=counting)
    assert calls.count(("s6", 1)) == 1 and ("s6", 2) not in calls
    reused = [e for e in events(result, "contract_frozen") if e["step_id"] == "s6" and e["attempt"] == 2]
    assert reused[0]["reference_reused"] is True


def test_retry_regenerates_the_reference_when_preconditions_changed(sim_cell, demo_plan, tmp_path):
    calls = []

    def counting(initial, contract, cell):
        calls.append((contract.step_id, contract.attempt))
        return simulated_reference(initial, contract, cell)

    world = SimWorld(SCENARIOS["grasp_failed"], sim_cell)
    motion = SimMotion(world)
    original = motion.execute

    def execute(command):
        outcome = original(command)
        if (command.action, command.piece_id, command.attempt) == ("pick", "B", 1):
            world.put("A", "right")
        return outcome

    motion.execute = execute
    run_scenario(SCENARIOS["grasp_failed"], sim_cell, demo_plan, tmp_path, reference=counting,
                 world=world, motion=motion)
    assert ("s6", 2) in calls


def test_software_stop_prevents_further_commands(sim_cell, demo_plan, tmp_path):
    engine = None

    class StoppingMotion(SimMotion):
        def execute(self, command):
            outcome = super().execute(command)
            engine.request_stop("parada de software del operador")
            return outcome

    world = SimWorld(SCENARIOS["success"], sim_cell)
    store = RunStore(tmp_path, "r-stop", Mode.SIMULATION, synthetic=True)
    engine = Engine(sim_cell, demo_plan, StoppingMotion(world), SimCamera(world), store,
                    EngineConfig(mode=Mode.SIMULATION, reference=simulated_reference))
    result = engine.run()
    assert (result.status, result.failure_class) == ("stopped", "operator_stop")
    assert sum(1 for e in events(result, "command_sent")) == 1


def test_disabled_motion_never_reaches_a_command(sim_cell, demo_plan, tmp_path):
    world = SimWorld(SCENARIOS["success"], sim_cell)
    store = RunStore(tmp_path, "r-disabled", Mode.SIMULATION, synthetic=True)
    with pytest.raises(MotionDisabled):
        DisabledMotion().execute(None)
    result = Engine(sim_cell, demo_plan, DisabledMotion(), SimCamera(world), store,
                    EngineConfig(mode=Mode.SIMULATION, reference=simulated_reference)).run()
    assert (result.status, result.failure_class) == ("stopped", "motion_disabled")


def test_frame_from_the_wrong_context_is_not_measured(sim_cell, demo_plan, tmp_path):
    world = SimWorld(SCENARIOS["success"], sim_cell)

    class StaleCamera(SimCamera):
        def capture(self, request):
            frame = super().capture(request)
            if request.phase == "post":
                return frame.model_copy(update={"token": "token-viejo"})
            return frame

    store = RunStore(tmp_path, "r-stale", Mode.SIMULATION, synthetic=True)
    result = Engine(sim_cell, demo_plan, SimMotion(world), StaleCamera(world), store,
                    EngineConfig(mode=Mode.SIMULATION, reference=simulated_reference)).run()
    assert (result.status, result.failure_class) == ("stopped", "unknown_state")
    rejected = [e for e in result_events(store) if e["event"] == "frame_rejected"]
    assert rejected and "stale_token" in rejected[0]["issues"]


def result_events(store):
    return [json.loads(line) for line in (store.path / "events.jsonl").read_text(encoding="utf-8").splitlines()]


def test_four_state_layers_stay_separate(sim_cell, demo_plan, tmp_path):
    result = run(sim_cell, demo_plan, tmp_path, "wrong_piece")
    state = result.state
    assert state["requested"]["B"] == "center"
    assert state["commanded"][-1]["action"] == "place" and state["commanded"][-1]["piece_id"] == "B"
    assert state["observed"]["center"] == "C"
    assert any("center" in item for item in state["uncertainty"])


@pytest.mark.parametrize("verdict, attempt, observed, expected", [
    (Verdict(outcome="pass", reasons=[]), 1, 0, "continue"),
    (Verdict(outcome="unknown", reasons=["x"]), 1, 0, "reobserve"),
    (Verdict(outcome="unknown", reasons=["x"]), 1, 1, "stop"),
    (Verdict(outcome="fail", reasons=["x"], failure_class="grasp_failed"), 1, 0, "retry"),
    (Verdict(outcome="fail", reasons=["x"], failure_class="grasp_failed"), 2, 0, "stop"),
    (Verdict(outcome="fail", reasons=["x"], failure_class="wrong_piece"), 1, 0, "stop"),
    (Verdict(outcome="fail", reasons=["x"], failure_class="missing_piece"), 1, 0, "stop"),
    (Verdict(outcome="fail", reasons=["x"], failure_class="ambiguous_state"), 1, 0, "stop"),
])
def test_decision_policy_transitions(verdict, attempt, observed, expected, sim_cell):
    assert next_action(verdict, attempt, observed, sim_cell.limits) == expected


def test_replay_reproduces_the_decisions_without_touching_a_world(sim_cell, demo_plan, tmp_path):
    from premonition.scenarios import replay_run

    original = run(sim_cell, demo_plan, tmp_path / "a", "grasp_failed")
    replayed = replay_run(original.store.path, sim_cell, tmp_path / "b")
    pick = lambda result: [(e["step_id"], e["attempt"], e["verdict"], e["next"]) for e in events(result, "decision")]
    assert pick(replayed) == pick(original)
    assert replayed.status == original.status
    manifest = json.loads((replayed.store.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "replay" and manifest["replay_of"] == original.store.run_id


def test_replay_never_issues_a_motion_port_call_to_a_real_transport(sim_cell, demo_plan, tmp_path):
    from premonition.scenarios import ReplayMotion

    original = run(sim_cell, demo_plan, tmp_path, "success")
    motion = ReplayMotion(events(original, "motion_result"))
    outcome = motion.execute(type("C", (), {"command_id": "x", "step_id": "s2", "attempt": 1})())
    assert isinstance(outcome, MotionResult) and motion.kind == "replay"
