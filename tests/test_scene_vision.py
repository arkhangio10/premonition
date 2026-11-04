import hashlib
import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from premonition.meta import MetaError, SamRecord
from premonition.scene_vision import (analyze_scene, apply_gripper_selection, latest_scene,
                                     load_capture, object_evidence, save_scene, segment_gripper_region)


UNDERSTANDING = {"summary": "A blue robot arm and an orange sponge on the table.",
                 "gripper_detail": "limited", "workpiece_visible": True,
                 "observations": ["The sponge is on the table."],
                 "limitations": ["The jaw gap is small in this view."],
                 "next_observation": "Observe the gripper from closer to the side."}


@pytest.fixture
def camera(tmp_path):
    folder = tmp_path / "real" / "captures"
    folder.mkdir(parents=True)
    jpeg = cv2.imencode(".jpg", np.full((40, 60, 3), 128, np.uint8))[1].tobytes()
    (folder / "real.jpg").write_bytes(jpeg)
    return tmp_path, {"file": "real.jpg", "sha256": hashlib.sha256(jpeg).hexdigest(),
                      "width": 60, "height": 40, "source": "jetson"}, jpeg


def observer(fail_sam=False, result=None):
    calls = []

    def vision(system, context, images, schema, name):
        calls.append(("muse", images, json.loads(context)))
        return json.dumps(UNDERSTANDING if result is None else result)

    def segment(jpeg, phrase):
        calls.append(("sam", jpeg, phrase))
        if fail_sam:
            raise MetaError(503, "test-key unavailable")
        return [SamRecord("0", (1, 2, 7, 8), None, (6, 6), bytes([1]*36))]

    return SimpleNamespace(api_key="test-key", vision_json=vision, segment=segment), calls


def test_same_real_image_reaches_muse_and_both_sam_prompts(camera):
    root, capture, jpeg = camera
    client, calls = observer()
    report = analyze_scene(client, root, capture)
    assert calls[0][1] == [("Current real camera image", jpeg)]
    assert [c[1] for c in calls[1:]] == [jpeg, jpeg]
    assert [c[2] for c in calls[1:]] == ["robot gripper", "orange sponge"]
    assert report["capture"]["sha256"] == capture["sha256"]
    assert report["actuators_used"] is report["synthetic_input"] is False
    assert report["objects"][0]["area_pixels"] == 36
    assert report["objects"][0]["confidence"] is None
    assert all(1 <= p[0] < 7 and 2 <= p[1] < 8 for p in report["objects"][0]["outlines"][0])
    save_scene(root, report)
    assert latest_scene(root)["id"] == report["id"]


@pytest.mark.parametrize("override", [{"source": "synthetic"}, {"file": "../real.jpg"},
                                      {"sha256": "0"*64}, {"width": 61}])
def test_invalid_or_altered_evidence_is_rejected_before_api_calls(camera, override):
    root, capture, _ = camera
    client, calls = observer()
    with pytest.raises(ValueError):
        analyze_scene(client, root, capture | override)
    assert calls == []


def test_failed_sam_is_visible_and_does_not_invent_objects(camera):
    root, capture, _ = camera
    client, _ = observer(fail_sam=True)
    report = analyze_scene(client, root, capture)
    assert report["objects"] == []
    assert all(s["status"] == "failed" for s in report["segmentation"])
    assert "test-key" not in json.dumps(report)


def test_motion_fields_are_not_accepted_in_scene_result(camera):
    root, capture, _ = camera
    client, calls = observer(result=UNDERSTANDING | {"servo_pulses": [1500]*6})
    with pytest.raises(ValidationError):
        analyze_scene(client, root, capture)
    assert len(calls) == 1


@pytest.mark.parametrize("record", [SamRecord("0", (-1, 2, 7, 8), None, (6, 6), b"x"*36),
                                    SamRecord("0", (1, 2, 70, 8), None, (6, 6), b"x"*36),
                                    SamRecord("0", (1, 2, 7, 8), None, (5, 6), b"x"*30)])
def test_sam_coordinates_and_mask_alignment_must_match_source(record):
    with pytest.raises(ValueError):
        object_evidence(record, "gripper", 60, 40)


def test_saved_analysis_is_hidden_if_its_photo_is_altered(camera):
    root, capture, _ = camera
    client, _ = observer()
    save_scene(root, analyze_scene(client, root, capture))
    (root / "real/captures/real.jpg").write_bytes(b"changed")
    assert latest_scene(root) is None


def test_assisted_gripper_uses_official_box_prompt_in_original_image_coordinates(camera):
    root,capture,jpeg = camera
    client,calls = observer()
    objects,box = segment_gripper_region(client,root,{"capture":capture},{"x":1,"y":2,"w":20,"h":20})
    assert box == [1,2,21,22]
    assert calls == [("sam",jpeg,"<0f>0<|box;x1=1;y1=2;x2=20;y2=21;w=60;h=40|>")]
    assert len(objects) == 1


def test_assisted_result_preserves_zero_automatic_matches_and_original_report(camera):
    root,capture,_=camera
    client,_=observer()
    parent=analyze_scene(client,root,capture)
    parent["segmentation"][0]["count"]=0
    saved=json.dumps(parent,sort_keys=True)
    result=apply_gripper_selection(parent,[{"role":"gripper"}],[1,2,21,22],[{"usd":.0025}])
    assert json.dumps(parent,sort_keys=True)==saved
    assert result["automatic_gripper_result"]["count"]==0
    assert result["segmentation"][-1]["prompt_type"]=="box"
    assert result["parent_scene_id"]==parent["id"] and result["id"]!=parent["id"]
    repeated=apply_gripper_selection(result,[{"role":"gripper"}],[2,3,22,23],[])
    assert repeated["automatic_gripper_result"]["count"]==0


def test_invalid_gripper_selection_does_not_call_sam(camera):
    root,capture,_=camera
    client,calls=observer()
    with pytest.raises(ValueError):
        segment_gripper_region(client,root,{"capture":capture},{"x":55,"y":2,"w":20,"h":20})
    assert calls==[]


@pytest.mark.parametrize("valid",[True,False])
def test_muse_box_can_guide_sam_without_inventing_a_mask(camera,valid):
    root,capture,jpeg=camera
    calls=[]
    proposal={"x1_px":1,"y1_px":2,"x2_px":21,"y2_px":22} if valid else {"x1_px":55,"y1_px":2,"x2_px":75,"y2_px":22}
    def vision(system,context,images,schema,name):
        assert "gripper_box" in schema["required"]
        assert "default" not in schema["properties"]["gripper_box"]
        return json.dumps(UNDERSTANDING|{"gripper_box":proposal})
    def segment(image,prompt):
        assert image==jpeg
        calls.append(prompt)
        if prompt=="robot gripper":return []
        return [SamRecord("0",(1,2,7,8),None,(6,6),bytes([1]*36))]
    client=SimpleNamespace(api_key="test-key",vision_json=vision,segment=segment)
    report=analyze_scene(client,root,capture)
    gripper=next(s for s in report["segmentation"] if s["role"]=="gripper")
    if valid:
        assert gripper["prompt_type"]=="model_box" and gripper["count"]==1
        assert report["automatic_gripper_result"]["count"]==0
        assert len(calls)==3 and calls[1].startswith("<0f>0<|box;")
    else:
        assert gripper["count"]==0 and gripper["guidance_error"]
        assert len(calls)==2
        assert not any(o["role"]=="gripper" for o in report["objects"])
