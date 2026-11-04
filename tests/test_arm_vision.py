import base64
import copy
import hashlib
import json

import cv2
import httpx
import numpy as np
import pytest
from pydantic import ValidationError

from premonition.arm_vision import analyze_trial, load_context
from premonition.meta import Budget, BudgetExceeded, MetaClient, MetaError

TRIAL = "a" * 32
READING = {"mode1": 33, "prescale": 121, "commanded_us": {
    "base": 1499, "shoulder": 1450, "elbow": 1499, "wrist_pitch": 1602,
    "wrist_roll": 1655, "gripper": 1616}}
RESULT = {"scene_summary": "A robot arm on a table.", "wrist_view_change": "visible",
          "gripper_change": "uncertain", "evidence": ["The wrist orientation differs."],
          "limitations": ["The jaws are blurred."], "next_observation": "Focus the camera.", "confidence": 0.4}


@pytest.fixture
def evidence(tmp_path):
    captures = tmp_path / "real" / "captures"
    captures.mkdir(parents=True)
    jpeg = cv2.imencode(".jpg", np.full((40, 60, 3), 128, dtype=np.uint8))[1].tobytes()
    frames = []
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        (captures / name).write_bytes(jpeg)
        frames.append({"file": name, "sha256": hashlib.sha256(jpeg).hexdigest()})
    after = copy.deepcopy(READING)
    after["commanded_us"]["gripper"] = 1499
    trial = {"before_capture": frames[0], "before_readback": READING,
             "steps": [{"command": {"targets": after["commanded_us"]},
                        "before_capture": frames[1], "after_capture": frames[2],
                        "before_readback": READING, "after_readback": after}]}
    path = tmp_path / "real" / "calibration" / "trials" / f"{TRIAL}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(trial), encoding="utf-8")
    return tmp_path, path, jpeg


def meta(handler):
    return MetaClient("test-key", Budget(1, 0.10),
                      http=httpx.Client(base_url="https://api.meta.ai/v1", transport=httpx.MockTransport(handler)))


def response(result):
    return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}],
                                    "usage": {"prompt_tokens": 100, "completion_tokens": 100}})


def test_real_image_bytes_and_order_reach_muse_with_context(evidence):
    root, _, jpeg = evidence
    requests = []

    def handler(request):
        requests.append(request)
        return response(RESULT)

    client = meta(handler)
    report = analyze_trial(client, root, TRIAL)
    body = json.loads(requests[0].content)
    assert body["model"] == "muse-spark-1.3"
    content = body["messages"][1]["content"]
    attached = [part["image_url"]["url"] for part in content if part["type"] == "image_url"]
    assert attached == ["data:image/jpeg;base64," + base64.b64encode(jpeg).decode()] * 3
    assert [f["file"] for f in report["frames"]] == ["a.jpg", "b.jpg", "c.jpg"]
    assert report["analysis"]["gripper_change"] == "uncertain"
    assert report["actuators_used_by_analysis"] is False
    assert (root / "real/calibration/vision" / f"{TRIAL}.json").is_file()
    with pytest.raises(BudgetExceeded):
        analyze_trial(client, root, TRIAL)
    assert len(requests) == 1


def test_tampered_camera_evidence_is_rejected_before_any_request(evidence):
    root, _, _ = evidence
    (root / "real/captures/b.jpg").write_bytes(b"tampered")
    sent = []
    with pytest.raises(ValueError, match="integrity"):
        analyze_trial(meta(lambda request: sent.append(request)), root, TRIAL)
    assert sent == []


def test_comparison_cannot_hide_a_changed_wrist(evidence):
    root, path, _ = evidence
    trial = json.loads(path.read_text())
    trial["steps"][0]["after_readback"]["commanded_us"]["wrist_roll"] += 80
    path.write_text(json.dumps(trial))
    with pytest.raises(ValueError, match="another joint"):
        load_context(root, TRIAL)


@pytest.mark.parametrize("name", ["../private.jpg", "C:/private.jpg"])
def test_context_cannot_upload_arbitrary_files(evidence, name):
    root, path, _ = evidence
    trial = json.loads(path.read_text())
    trial["before_capture"]["file"] = name
    path.write_text(json.dumps(trial))
    with pytest.raises(ValueError, match="filename"):
        load_context(root, TRIAL)


def test_model_cannot_smuggle_a_motion_command_into_analysis(evidence):
    root, _, _ = evidence
    with pytest.raises(ValidationError):
        analyze_trial(meta(lambda r: response(RESULT | {"command": {"cmd": "move"}})), root, TRIAL)
    assert not (root / "real/calibration/vision" / f"{TRIAL}.json").exists()


def test_truncated_generation_is_not_saved_as_valid_analysis(evidence):
    root, _, _ = evidence
    reply = httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]})
    with pytest.raises(MetaError, match="incomplete"):
        analyze_trial(meta(lambda r: reply), root, TRIAL)
    assert not (root / "real/calibration/vision" / f"{TRIAL}.json").exists()


def test_web_reads_saved_analysis_without_new_model_or_hardware_calls(evidence, monkeypatch):
    from fastapi.testclient import TestClient
    from premonition import web

    root, _, _ = evidence
    analyze_trial(meta(lambda r: response(RESULT)), root, TRIAL)
    def blocked(*args, **kwargs):
        pytest.fail("Reading saved analysis must not call hardware or a model")
    monkeypatch.setattr(web, "client_from_env", lambda **kwargs: None)
    monkeypatch.setattr(web.jetson_link, "read_commanded_pulses", blocked)
    monkeypatch.setattr(MetaClient, "vision_json", blocked)
    client = TestClient(web.create_app(root), base_url="http://127.0.0.1")
    status = client.get("/api/calibration").json()
    assert status["vision_analysis"]["analysis"]["gripper_change"] == "uncertain"
    assert status["motion_enabled"] is False
