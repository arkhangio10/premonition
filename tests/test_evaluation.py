import json

import pytest

from premonition.evaluation import ThresholdsChanged, assign_splits, collect_trials, evaluate
from premonition.scenarios import replay_run, run_scenario
from premonition.sim import SCENARIOS


def test_fixture_version_change_preserves_the_previous_recording(sim_cell, demo_plan, tmp_path):
    from premonition.scenarios import FIXTURE_VERSION, record_fixture

    path = record_fixture(tmp_path, "success", sim_cell, demo_plan)
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["fixture_version"] = "legacy"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    frame = next((path / "frames").glob("*.jpg"))
    original = frame.read_bytes()
    record_fixture(tmp_path, "success", sim_cell, demo_plan)
    archived = next((tmp_path / "fixtures" / "archive").glob("fixture-success-*"))
    assert (archived / "frames" / frame.name).read_bytes() == original
    assert json.loads((archived / "manifest.json").read_text(encoding="utf-8"))["fixture_version"] == "legacy"
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["fixture_version"] == FIXTURE_VERSION


@pytest.fixture
def recorded(sim_cell, demo_plan, tmp_path):
    def record(*names):
        return [run_scenario(SCENARIOS[name], sim_cell, demo_plan, tmp_path).store.path for name in names]
    return record


def test_a2_and_a3_are_judged_on_exactly_the_same_trials(recorded, sim_cell):
    trials, _ = collect_trials(recorded("success", "wrong_piece"), sim_cell)
    assert trials and all(t.a2 is not None and t.a3 is not None for t in trials)
    report = evaluate(recorded("success"), sim_cell)
    assert report["methods"]["A2"]["trials"] == report["methods"]["A3"]["trials"]


def test_evaluation_is_reproducible(recorded, sim_cell):
    runs = recorded("success", "grasp_failed", "wrong_piece")
    assert evaluate(runs, sim_cell) == evaluate(runs, sim_cell)


def test_denominators_are_explicit_and_count_real_failures(recorded, sim_cell):
    report = evaluate(recorded("wrong_piece"), sim_cell)
    a2 = report["methods"]["A2"]
    # El agarre de la pieza equivocada vacía el origen: A2 lo acepta aunque físicamente es un fallo.
    assert a2["failures_accepted"] == {"num": 1, "den": 2}
    assert a2["failures_accepted_share_of_acceptances"]["den"] == a2["acceptances"]
    assert a2["abstentions"]["den"] == a2["trials"]


def test_correct_runs_have_no_rejections_in_the_synthetic_scene(recorded, sim_cell):
    report = evaluate(recorded("success"), sim_cell)
    assert report["methods"]["A2"]["correct_rejected"]["num"] == 0
    assert report["methods"]["A2"]["failures_accepted"]["den"] == 0


def test_changed_thresholds_invalidate_recorded_runs(recorded, sim_cell):
    runs = recorded("success")
    changed = sim_cell.perception.model_copy(update={"occupied_min": 0.5})
    with pytest.raises(ThresholdsChanged):
        evaluate(runs, sim_cell.model_copy(update={"perception": changed}))


def test_trial_without_label_is_excluded_and_reported(recorded, sim_cell):
    run = recorded("success")[0]
    labels = json.loads((run / "labels.json").read_text(encoding="utf-8"))
    labels.pop(next(iter(labels)))
    (run / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    _, excluded = collect_trials([run], sim_cell)
    assert [item["reason"] for item in excluded] == ["no_label"]


def test_labels_from_the_verifier_itself_are_refused(recorded, sim_cell):
    run = recorded("success")[0]
    labels = json.loads((run / "labels.json").read_text(encoding="utf-8"))
    for entry in labels.values():
        entry["annotator"] = "verifier"
    (run / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    trials, excluded = collect_trials([run], sim_cell)
    assert trials == [] and {item["reason"] for item in excluded} == {"label_not_independent"}


def test_tampered_reference_is_excluded(recorded, sim_cell):
    run = recorded("success")[0]
    (run / "references" / "s2-1-post.jpg").write_bytes(b"otra imagen elegida despues")
    _, excluded = collect_trials([run], sim_cell)
    assert {"contract": "s2-1-post", "reason": "reference_changed"} in [
        {key: item[key] for key in ("contract", "reason")} for item in excluded]


def test_reference_frozen_after_the_action_is_excluded(recorded, sim_cell):
    run = recorded("success")[0]
    events = [json.loads(line) for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    first_command = next(e for e in events if e["event"] == "command_sent")
    frozen = next(e for e in events if e["event"] == "contract_frozen")
    frozen["seq"], first_command["seq"] = first_command["seq"], frozen["seq"]
    (run / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    _, excluded = collect_trials([run], sim_cell)
    assert "not_frozen_before_action" in {item["reason"] for item in excluded}


def test_replays_never_count_as_new_trials(recorded, sim_cell, tmp_path):
    run = recorded("success")[0]
    replayed = replay_run(run, sim_cell, tmp_path / "replays").store.path
    assert evaluate([run, replayed], sim_cell)["kits"]["attempted"] == 1


def test_recovery_is_reported_per_failure_class(recorded, sim_cell):
    report = evaluate(recorded("grasp_failed", "grasp_failed_persistent"), sim_cell)
    assert report["recovery"]["grasp_failed"] == {"num": 1, "den": 2}


def test_kits_are_counted_separately_from_detection(recorded, sim_cell):
    report = evaluate(recorded("success", "missing_piece"), sim_cell)
    assert report["kits"] == {"completed": 1, "attempted": 2}


def test_report_declares_synthetic_provenance(recorded, sim_cell):
    report = evaluate(recorded("success"), sim_cell)
    assert report["provenance"] == {"synthetic_runs": 1, "real_runs": 0}
    assert "no son evidencia" in report["warning"]


def test_composition_is_reported(recorded, sim_cell):
    report = evaluate(recorded("success", "misplaced"), sim_cell)
    assert report["composition"]["scenarios"] == {"misplaced": 1, "success": 1}
    assert report["composition"]["failure_classes"]["misplaced"] >= 1


def test_splits_never_divide_a_run_and_are_stable():
    runs = [f"run-{n}" for n in range(40)]
    first, second = assign_splits(runs), assign_splits(list(reversed(runs)))
    assert first == second and set(first) == set(runs)
    assert set(first.values()) == {"development", "calibration", "evaluation"}


def test_a3_matches_a2_on_a_run_where_the_reference_agrees(recorded, sim_cell):
    methods = evaluate(recorded("success"), sim_cell)["methods"]
    assert methods["A3"] == methods["A2"]
