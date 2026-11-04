import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from premonition.meta import Budget, MetaClient


@pytest.fixture
def scene_app(tmp_path, monkeypatch):
    from premonition import web
    client = MetaClient("fake-key", Budget(3, .2))
    monkeypatch.setattr(web, "client_from_env", lambda **kw: client)
    captures = []
    folder = tmp_path / "real/captures"
    folder.mkdir(parents=True)

    def capture(host, root):
        name = f"frame-{len(captures)}.jpg"
        jpeg = cv2.imencode(".jpg", np.full((40, 60, 3), 128, np.uint8))[1].tobytes()
        (folder/name).write_bytes(jpeg)
        result = {"file": name, "source": "jetson", "width": 60, "height": 40,
                  "sha256": hashlib.sha256(jpeg).hexdigest()}
        captures.append(result)
        return result

    monkeypatch.setattr(web.jetson_link, "capture_to_disk", capture)

    def analyze(observer, root, photo):
        return {"id": "a"*32, "created_at": "2026-11-02T17:00:00+00:00", "capture": photo,
                "synthetic_input": False, "actuators_used": False,
                "source": "muse-spark-1.3", "segmentation_source": "sam-3.1", "objects": [], "segmentation": [],
                "understanding": {"summary": "A real arm.", "gripper_detail": "uncertain", "workpiece_visible": False,
                                  "observations": [], "limitations": [], "next_observation": "Inspect the jaws."}}

    monkeypatch.setattr(web, "analyze_scene", analyze)
    app = TestClient(web.create_app(tmp_path), base_url="http://127.0.0.1")
    yield app, captures, analyze
    client.http.close()


def test_scene_requires_meta_without_touching_the_camera(tmp_path, monkeypatch):
    from premonition import web
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    def refuse(*args):
        pytest.fail("Camera should not run without Meta configured")
    monkeypatch.setattr(web.jetson_link, "capture_to_disk", refuse)
    app = TestClient(web.create_app(tmp_path), base_url="http://127.0.0.1")
    assert app.post("/api/calibration/analyze-scene").status_code == 409


def test_analysis_captures_a_new_photo_and_persists_readonly_result(scene_app):
    app, captures, _ = scene_app
    assert app.get("/api/calibration").json()["scene_analysis"] is None
    assert captures == []
    first = app.post("/api/camera/capture").json()
    response = app.post("/api/calibration/analyze-scene")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["report"]["capture"]["file"] != first["file"]
    assert result["report"]["capture"] == captures[-1]
    assert result["status"]["capture"] == captures[-1]
    assert app.get("/api/calibration").json()["scene_analysis"]["id"] == "a"*32
    assert len(captures) == 2


def test_concurrent_analysis_is_rejected_without_a_second_capture(scene_app, monkeypatch):
    from premonition import web
    app, captures, analyze = scene_app
    entered, release = threading.Event(), threading.Event()
    def hold(*args):
        entered.set()
        assert release.wait(5)
        return analyze(*args)
    monkeypatch.setattr(web, "analyze_scene", hold)
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(app.post, "/api/calibration/analyze-scene")
        try:
            assert entered.wait(3)
            assert app.post("/api/calibration/analyze-scene").status_code == 409
            assert len(captures) == 1
        finally:
            release.set()
        assert running.result(timeout=3).status_code == 200


def test_failed_analysis_releases_lock_and_does_not_create_a_fake_result(scene_app, monkeypatch):
    from premonition import web
    app, _, analyze = scene_app
    def failure(*args):
        raise ValueError("invalid response")
    monkeypatch.setattr(web, "analyze_scene", failure)
    assert app.post("/api/calibration/analyze-scene").status_code == 502
    assert app.get("/api/calibration").json()["scene_analysis"] is None
    monkeypatch.setattr(web, "analyze_scene", analyze)
    assert app.post("/api/calibration/analyze-scene").status_code == 200


def workspace_body(capture):
    return {"capture_file": capture["file"], "capture_sha256": capture["sha256"],
            "source": {"x": 1, "y": 2, "w": 10, "h": 10},
            "destination": {"x": 30, "y": 20, "w": 15, "h": 15}, "operator_observed": True}


def test_regions_save_without_an_api_call_or_motion_and_keep_photo_provenance(scene_app):
    app, captures, _ = scene_app
    capture = app.post("/api/camera/capture").json()
    response = app.post("/api/calibration/workspace", json=workspace_body(capture))
    assert response.status_code == 200, response.text
    report = response.json()["workspace"]
    assert report["capture"] == capture
    assert report["operator_marked"] is True and report["motion_calibrated"] is False
    assert app.get("/api/calibration").json()["workspace_regions"]["id"] == report["id"]
    assert len(captures) == 1


@pytest.mark.parametrize("change,status", [
    ({"destination": {"x": 2, "y": 3, "w": 10, "h": 10}}, 422),
    ({"destination": {"x": 55, "y": 20, "w": 15, "h": 15}}, 422),
    ({"operator_observed": False}, 422),
    ({"capture_sha256": "0"*64}, 409),
    ({"servo_targets": [1500]*6}, 422),
])
def test_regions_reject_overlap_bounds_unconfirmed_stale_or_extra_data(scene_app, change, status):
    app, _, _ = scene_app
    capture = app.post("/api/camera/capture").json()
    response = app.post("/api/calibration/workspace", json=workspace_body(capture) | change)
    assert response.status_code == status, response.text
    assert app.get("/api/calibration").json()["workspace_regions"] is None


def test_regions_from_a_previous_photo_are_not_silently_attached_to_a_new_one(scene_app):
    app, _, _ = scene_app
    first = app.post("/api/camera/capture").json()
    app.post("/api/camera/capture")
    assert app.post("/api/calibration/workspace", json=workspace_body(first)).status_code == 409


def test_restart_restores_verified_analyzed_photo_without_capturing_or_calling_meta(scene_app, tmp_path):
    from premonition import web
    app, captures, _ = scene_app
    analyzed = app.post("/api/calibration/analyze-scene").json()["report"]
    restarted = TestClient(web.create_app(tmp_path), base_url="http://127.0.0.1")
    restored = restarted.get("/api/calibration").json()["capture"]
    assert restored["file"] == analyzed["capture"]["file"] and restored["restored"] is True
    assert "quality" in restored
    assert len(captures) == 1
    fresh = restarted.post("/api/camera/capture").json()
    assert "restored" not in fresh and fresh["file"] != restored["file"]


def test_prepared_proposal_is_available_for_review_and_is_never_approval(scene_app, tmp_path):
    app, captures, _ = scene_app
    capture = app.post("/api/camera/capture").json()
    proposal = {"capture": capture, "source": workspace_body(capture)["source"],
                "destination": workspace_body(capture)["destination"],
                "operator_confirmed": False, "motion_calibrated": False}
    folder = tmp_path / "real/calibration"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "workspace_proposal_test.json").write_text(json.dumps(proposal), encoding="utf-8")
    status = app.get("/api/calibration").json()
    assert status["workspace_proposal"] == proposal
    assert status["workspace_regions"] is None
    assert len(captures) == 1


def test_altered_proposal_photo_is_not_offered_for_review(scene_app, tmp_path):
    app, _, _ = scene_app
    capture = app.post("/api/camera/capture").json()
    proposal = {"capture": capture | {"sha256": "0"*64}, "source": workspace_body(capture)["source"],
                "destination": workspace_body(capture)["destination"],
                "operator_confirmed": False, "motion_calibrated": False}
    folder = tmp_path / "real/calibration"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "workspace_proposal_test.json").write_text(json.dumps(proposal), encoding="utf-8")
    assert app.get("/api/calibration").json()["workspace_proposal"] is None


def test_assisted_selection_requires_current_analyzed_photo(scene_app,monkeypatch):
    from premonition import web
    app,_,_=scene_app
    called=[]
    def segment(*args):
        called.append(args)
        return [],[1,2,21,22]
    monkeypatch.setattr(web,"segment_gripper_region",segment)
    capture=app.post("/api/camera/capture").json()
    body={"capture_file":capture["file"],"capture_sha256":capture["sha256"],"region":{"x":1,"y":2,"w":20,"h":20}}
    assert app.post("/api/calibration/select-gripper",json=body).status_code==409
    assert called==[]
    analyzed=app.post("/api/calibration/analyze-scene").json()["report"]
    body.update(capture_file=analyzed["capture"]["file"],capture_sha256=analyzed["capture"]["sha256"])
    response=app.post("/api/calibration/select-gripper",json=body)
    assert response.status_code==200,response.text
    assert response.json()["report"]["segmentation"][-1]["prompt_type"]=="box"
    app.post("/api/camera/capture")
    assert app.post("/api/calibration/select-gripper",json=body).status_code==409
    assert len(called)==1
