import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from premonition.cell import load_cell
from premonition.teaching import PoseNotReady, load_poses, pose_blockers, record_pose
from premonition.web import create_app

CELL = load_cell(Path(__file__).resolve().parent.parent / "config" / "cell.json")


def active_reading():
    return {"mode1": 33, "prescale": 121, "commanded_us": dict.fromkeys(CELL.joints, 1500)}


def test_page_and_initial_status_do_not_access_hardware(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Hardware access during initial page/status")
    monkeypatch.setattr("premonition.jetson.check_connection", forbidden)
    monkeypatch.setattr("premonition.jetson.read_commanded_pulses", forbidden)
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    assert client.get("/calibration").status_code == 200
    status = client.get("/api/calibration").json()
    assert status["controller"] is None and status["motion_enabled"] is False
    assert status["poses"] == [] and status["pose_blockers"]
    assert client.post("/api/calibration/poses", json={"name": "Pose", "expected": active_reading()["commanded_us"], "operator_observed": True}).status_code == 409


@pytest.mark.parametrize("change", ["sleep", "frequency", "released", "out_of_bounds", "missing_joint"])
def test_unsafe_or_incomplete_readings_cannot_be_recorded(tmp_path, change):
    reading = active_reading()
    if change == "sleep": reading["mode1"] |= 16
    if change == "frequency": reading["prescale"] = 30
    if change == "released": reading["commanded_us"]["gripper"] = None
    if change == "out_of_bounds": reading["commanded_us"]["base"] = 2400
    if change == "missing_joint": del reading["commanded_us"]["elbow"]
    assert pose_blockers(reading, CELL)
    with pytest.raises(PoseNotReady):
        record_pose(tmp_path, CELL, "Pose", reading["commanded_us"], reading, reading, True)
    assert load_poses(tmp_path) == []


def test_recording_requires_stability_and_operator_observation(tmp_path):
    reading = active_reading()
    changed = copy.deepcopy(reading)
    changed["commanded_us"]["gripper"] += 10
    for first, second, expected, observed in [
        (reading, reading, reading["commanded_us"], False),
        (reading, changed, reading["commanded_us"], True),
        (changed, changed, reading["commanded_us"], True),
    ]:
        with pytest.raises(PoseNotReady):
            record_pose(tmp_path, CELL, "Pose", expected, first, second, observed)
    assert load_poses(tmp_path) == []


def test_saved_pose_is_commanded_state_and_does_not_validate_a_route(tmp_path):
    reading = active_reading()
    pose = record_pose(tmp_path, CELL, "Observation", reading["commanded_us"], reading, reading, True)
    assert pose["targets_us"] == reading["commanded_us"]
    assert pose["source"] == "commanded_pulses" and pose["operator_observed"] is True
    assert load_poses(tmp_path) == [json.loads(json.dumps(pose))]
    with pytest.raises(PoseNotReady):
        record_pose(tmp_path, CELL, "observation", reading["commanded_us"], reading, reading, True)
    assert len(load_poses(tmp_path)) == 1


def test_endpoint_rereads_controller_and_refuses_changes(tmp_path, monkeypatch):
    reading = active_reading()
    monkeypatch.setattr("premonition.jetson.check_connection", lambda host: {"connected": True, "hostname": "test"})
    monkeypatch.setattr("premonition.jetson.read_commanded_pulses", lambda host: copy.deepcopy(reading))
    client = TestClient(create_app(tmp_path), base_url="http://127.0.0.1")
    assert client.post("/api/calibration/inspect").status_code == 200
    reading["commanded_us"]["base"] += 10
    response = client.post("/api/calibration/poses", json={"name": "Pose", "expected": active_reading()["commanded_us"], "operator_observed": True})
    assert response.status_code == 409
    assert load_poses(tmp_path) == []
    response = client.post("/api/calibration/poses", json={"name": "Pose", "expected": reading["commanded_us"], "operator_observed": True})
    assert response.status_code == 200 and response.json()["pose"]["name"] == "Pose"
