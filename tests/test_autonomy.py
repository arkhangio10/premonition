import json
import ast

import cv2
import numpy as np
import pytest
from pathlib import Path

from premonition import autonomy
from premonition.atlas import SCAN_GRID, predict_tip, serpentine
from premonition.autonomy import find_object, judge, plan_task, run_task, safe_destination
from premonition.dual_camera import Frame
from premonition.meta import Budget, MetaError, SamRecord

JOINTS = ("base", "shoulder", "elbow")
A = np.array([[1.2, 0.3, -0.1], [0.4, -2.0, 0.6], [0.1, 0.36, -0.16], [-0.2, -0.64, 0.57]])
B = np.array([-1100.0, 1900.0, 400.0, 300.0])
ATLAS = [{"pulses": p, "t": 0.0, "tip": {"c922": (A @ [p[j] for j in JOINTS] + B)[:2].tolist(),
                                          "usb": (A @ [p[j] for j in JOINTS] + B)[2:].tolist()}}
         for p in serpentine(dict(SCAN_GRID, base=[1150, 1250, 1350, 1450, 1550, 1650, 1750]))]
PICK = {"base": 1350, "shoulder": 1480, "elbow": 2290, "wrist_pitch": 1182, "wrist_roll": 1567, "gripper": 1382}
PLAN = {"object": "orange sponge", "destination": "beside the board", "destination_px": {"c922": [0, 0], "usb": [0, 0]},
        "obstacles": [], "feasible": True, "reason": "room on the table"}
VERDICT = {"success": False, "reason": "outer jaw landed on the top face", "next": "shift_outward"}


def frame(orange=None):
    image = np.full((1080, 1920, 3), (200, 200, 200), np.uint8)
    if orange:
        cv2.rectangle(image, orange[:2], orange[2:], (40, 130, 250), -1)
    return Frame(0.0, image, cv2.imencode(".jpg", cv2.resize(image, (1280, 720)))[1].tobytes())


class FakeClient:
    def __init__(self, replies=None, fail=None, boxes=()):
        self.replies, self.fail, self.boxes, self.calls = replies or {}, fail, boxes, []
        self.budget = Budget(20, 1.0)

    def vision_json(self, system, user, images, schema, schema_name, **options):
        self.calls.append(("vision", schema_name, images))
        if self.fail:
            raise self.fail
        return json.dumps(self.replies[schema_name])

    def segment(self, jpeg, phrase):
        self.calls.append(("segment", jpeg, phrase))
        return [SamRecord(str(i), box, confidence, (1, 1), b"") for i, (box, confidence) in enumerate(self.boxes)]


def test_plan_task_sends_both_views_and_parses_schema():
    client = FakeClient({"arm_task_plan": PLAN})
    plan = plan_task(client, "lleva la esponja junto a la placa", {"c922": frame(), "usb": frame()})
    assert plan == PLAN
    (kind, name, images), = client.calls
    assert [label.split()[0] for label, _ in images] == ["c922", "usb"]
    assert all(cv2.imdecode(np.frombuffer(jpeg, np.uint8), 1).shape == (1080, 1920, 3) for _, jpeg in images)


def default_destination():
    return {v: tuple(p) for v, p in predict_tip(ATLAS, dict(PICK, base=1700)).items()}


OBJ = {"c922": {"cx": 700, "cy": 900, "top": 800, "bottom": 1000, "x0": 600, "x1": 800, "area": 40000},
       "usb": {"cx": 700, "cy": 700, "top": 600, "bottom": 800, "x0": 600, "x1": 800, "area": 40000}}


def test_safe_destination_rejects_point_outside_image_and_uses_default():
    plan = dict(PLAN, destination_px={"c922": [500, 400], "usb": [2500, 100]})
    assert safe_destination(plan, PICK, OBJ, ATLAS) == default_destination()
    assert safe_destination(None, PICK, OBJ, ATLAS) == default_destination()
    assert safe_destination(dict(PLAN, feasible=False), PICK, OBJ, ATLAS) == default_destination()


def test_safe_destination_rejects_point_inside_object():
    plan = dict(PLAN, destination_px={"c922": [700, 900], "usb": [700, 700]})
    assert safe_destination(plan, PICK, OBJ, ATLAS) == default_destination()


def test_safe_destination_follows_a_valid_plan_point():
    wanted = predict_tip(ATLAS, dict(PICK, base=PICK["base"] + 180))
    plan = dict(PLAN, destination_px={v: [round(c) for c in p] for v, p in wanted.items()})
    chosen = safe_destination(plan, PICK, OBJ, ATLAS)
    assert chosen != default_destination()
    assert all(np.hypot(*np.subtract(chosen[v], wanted[v])) < 15 for v in ("c922", "usb"))


def test_judge_failure_falls_back_to_local_rule():
    frames = {"c922": frame(), "usb": frame()}
    verdict = judge(FakeClient(fail=MetaError(503, "busy")), "grasp", frames, frames)
    assert verdict["source"] == "local" and verdict["next"] is None and "busy" in verdict["reason"]
    assert judge(None, "grasp", frames, frames)["source"] == "local"
    sent = FakeClient({"arm_verdict": VERDICT})
    assert judge(sent, "grasp", frames, frames) == dict(VERDICT, source="muse")
    assert [label.split()[0] for label, _ in sent.calls[0][2]] == ["usb_before", "usb_after", "c922_after"]


class Cams:
    def snapshot(self, after=None, timeout=5.0):
        return {"c922": frame((600, 800, 800, 1000)), "usb": frame((600, 600, 800, 800))}


class Session:
    positions = dict(PICK, gripper=1616)


def skills(monkeypatch, offsets=None, client_advice=None):
    def grasp(session, cams, atlas, memory, advise=None, choose=None):
        if offsets is not None:
            offsets.append(advise(0))
        return {"ok": True, "reason": "lifted", "attempts": 1, "seconds": 1.0, "pick_pulses": PICK}

    def place(session, cams, atlas, destination, memory):
        return {"ok": True, "reason": "placed", "attempts": 1, "seconds": 1.0}
    monkeypatch.setattr(autonomy, "grasp", grasp)
    monkeypatch.setattr(autonomy, "place", place)


def test_run_task_completes_with_muse_unavailable(monkeypatch, tmp_path):
    skills(monkeypatch)
    result = run_task("lleva la esponja junto a la placa", Session(), Cams(), ATLAS, None, {}, tmp_path)
    assert result["ok"]
    log = json.loads((tmp_path / f"{result['run_id']}.json").read_text(encoding="utf-8"))
    assert log["muse"] == "unavailable" and log["phase"] == "done" and [s["phase"] for s in log["steps"]] == ["grasp", "place"]
    assert (tmp_path / "latest.jpg").exists()


def test_run_task_maps_shift_outward_to_negative_offset(monkeypatch, tmp_path):
    offsets = []
    skills(monkeypatch, offsets)
    client = FakeClient({"arm_task_plan": PLAN, "arm_verdict": VERDICT})
    result = run_task("lleva la esponja junto a la placa", Session(), Cams(), ATLAS, client, {}, tmp_path)
    assert result["ok"] and offsets == [-15]


def test_run_task_passes_the_chooser_and_logs_tries(monkeypatch, tmp_path):
    tries, received = [{"skill": "grasp", "class": "jaws_on_top"}] * 3, []

    def choose(attempts):
        return None

    def grasp(session, cams, atlas, memory, advise=None, choose=None):
        received.append(choose)
        return {"ok": False, "reason": "ask_human", "attempts": 3, "seconds": 1.0, "descents": [], "tries": tries,
                "help": "Turn the sponge."}
    monkeypatch.setattr(autonomy, "grasp", grasp)
    result = run_task("lleva la esponja junto a la placa", Session(), Cams(), ATLAS, None, {}, tmp_path, choose=choose)
    assert received == [choose] and not result["ok"] and result["reason"] == "grasp_ask_human"
    step, = json.loads((tmp_path / f"{result['run_id']}.json").read_text(encoding="utf-8"))["steps"]
    assert step["phase"] == "grasp" and step["tries"] == tries and step["help"] == "Turn the sponge."


def test_find_object_falls_back_to_sam_only_for_the_missing_view():
    client = FakeClient(boxes=[((100, 200, 300, 400), 0.9), ((0, 0, 10, 10), 0.2)])
    frames = {"c922": frame(), "usb": frame((600, 600, 800, 800))}
    found = find_object(client, frames, "orange sponge")
    assert [c[0] for c in client.calls] == ["segment"] and client.calls[0][1] == frames["c922"].jpeg
    assert found["c922"] == {"cx": 300.0, "cy": 450.0, "top": 300.0, "bottom": 600.0, "x0": 150.0, "x1": 450.0, "area": 90000.0}
    assert abs(found["usb"]["x0"] - 600) <= 5


@pytest.mark.parametrize("plan", [
    [], "not a plan", dict(PLAN, feasible="yes"), dict(PLAN, destination_px=[]),
    dict(PLAN, destination_px={"c922": ["500", 400], "usb": [500, 400]}),
    dict(PLAN, destination_px={"c922": [True, 400], "usb": [500, 400]}),
    dict(PLAN, destination_px={"c922": [500, 400], "usb": [500, float("nan")]}),
    dict(PLAN, destination_px={"c922": [500, 400], "usb": [500, 400], "extra": None}),
])
def test_safe_destination_falls_back_for_malformed_plan(plan):
    assert safe_destination(plan, PICK, OBJ, ATLAS) == default_destination()


@pytest.mark.parametrize("verdict", [[], "bad verdict", None,
    {"success": False, "reason": "bad next", "next": []},
    {"success": "false", "reason": "bad success", "next": "retry"},
    {"success": False, "reason": 42, "next": "retry"}])
def test_judge_malformed_reply_uses_local_checks(verdict):
    frames = {"c922": frame(), "usb": frame()}
    result = judge(FakeClient({"arm_verdict": verdict}), "grasp", frames, frames)
    assert result["source"] == "local" and result["next"] is None


@pytest.mark.parametrize("next_value", [[], {}])
def test_run_task_ignores_invalid_next(monkeypatch, tmp_path, next_value):
    offsets = []
    skills(monkeypatch, offsets)
    monkeypatch.setattr(autonomy, "judge", lambda *args: dict(VERDICT, next=next_value, source="muse"))
    result = run_task("move the sponge", Session(), Cams(), ATLAS,
                      FakeClient({"arm_task_plan": PLAN}), {}, tmp_path)
    assert result["ok"] and offsets == [None]


@pytest.mark.parametrize("phase", ["initial_photo", "grasp", "place"])
def test_run_task_finalizes_log_when_hardware_raises(monkeypatch, tmp_path, phase):
    skills(monkeypatch)

    def fail(*args, **kwargs):
        raise RuntimeError("camera or controller stopped")

    cams = Cams()
    if phase == "initial_photo":
        monkeypatch.setattr(cams, "snapshot", fail)
    else:
        monkeypatch.setattr(autonomy, phase, fail)
    with pytest.raises(RuntimeError, match="camera or controller stopped"):
        run_task("move the sponge", Session(), cams, ATLAS, None, {}, tmp_path)
    path, = tmp_path.glob("*.json")
    log = json.loads(path.read_bytes())
    assert log["phase"] == "done" and log["ok"] is False
    assert log["reason"].startswith("error:") and "camera or controller stopped" in log["reason"]


def test_run_task_publishes_complete_logs_atomically(monkeypatch, tmp_path):
    skills(monkeypatch)
    published = []
    replace = Path.replace

    def inspect_replace(source, target):
        if Path(target).suffix == ".json":
            new = json.loads(source.read_bytes())
            if Path(target).exists():
                json.loads(Path(target).read_bytes())
            published.append(new["phase"])
        return replace(source, target)

    monkeypatch.setattr(Path, "replace", inspect_replace)
    result = run_task("move the sponge", Session(), Cams(), ATLAS, None, {}, tmp_path)
    assert result["ok"] and {"planning", "grasp", "place", "done"} <= set(published)


def test_run_task_finalizes_an_operator_interrupt_before_reraising(monkeypatch, tmp_path):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(autonomy, "grasp", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_task("move the sponge", Session(), Cams(), ATLAS, None, {}, tmp_path)
    path, = tmp_path.glob("*.json")
    log = json.loads(path.read_bytes())
    assert log["phase"] == "done" and log["ok"] is False and "KeyboardInterrupt" in log["reason"]


@pytest.mark.parametrize("pick_base", [1260, 1650, 1700, 1750])
def test_default_place_uses_the_operator_approved_base(pick_base):
    pick = dict(PICK, base=pick_base)
    expected = {v: tuple(p) for v, p in predict_tip(ATLAS, dict(pick, base=1700)).items()}
    assert safe_destination(None, pick, OBJ, ATLAS) == expected


def test_default_place_refuses_an_atlas_that_does_not_cover_the_approved_base():
    partial = [p for p in ATLAS if p["pulses"]["base"] <= 1450]
    with pytest.raises(ValueError, match="approved place base.*atlas"):
        safe_destination(None, PICK, OBJ, partial)


def test_grasp_place_tool_uses_the_same_approved_destination():
    source = Path(__file__).parents[1] / "inspection/session_tools_20261103/grasp_place.py"
    tree = ast.parse(source.read_bytes())
    expression, = [n.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "destination" for t in n.targets)]
    chosen = eval(compile(ast.Expression(expression), str(source), "eval"),
                  {"safe_destination": safe_destination, "predict_tip": predict_tip, "dict": dict,
                   "atlas": ATLAS, "pick": dict(PICK, base=1700)})
    expected = predict_tip(ATLAS, dict(PICK, base=1700))
    assert all(np.allclose(chosen[v], expected[v]) for v in expected)


def test_planner_base_range_includes_the_approved_default():
    assert autonomy.BASE_RANGE_US[0] <= 1700 <= autonomy.BASE_RANGE_US[1]


def test_failed_grasp_keeps_the_muse_plan_and_phase_verdict(monkeypatch, tmp_path):
    monkeypatch.setattr(autonomy, "grasp", lambda *args, **kwargs:
                        {"ok": False, "reason": "object_not_found", "attempts": 2, "seconds": 1})
    client = FakeClient({"arm_task_plan": PLAN, "arm_verdict": VERDICT})
    result = run_task("move the sponge", Session(), Cams(), ATLAS, client, {}, tmp_path)
    log = json.loads((tmp_path / (result["run_id"] + ".json")).read_bytes())
    assert not result["ok"] and log["plan"] == PLAN
    assert len(log["verdicts"]) == 1 and log["verdicts"][0] == dict(VERDICT, source="muse", phase="grasp")


def test_phase_verdict_arriving_in_22_seconds_is_kept_within_client_timeout(monkeypatch, tmp_path):
    skills(monkeypatch)
    class Delayed:
        def __init__(self, value, delay):
            self.value, self.delay = value, delay
        def result(self, timeout):
            if timeout < self.delay:
                raise TimeoutError()
            return self.value
    class Pool:
        def submit(self, function, *args):
            return Delayed(function(*args), 22 if function is autonomy.judge else 0)
    monkeypatch.setattr(autonomy, "POOL", Pool())
    client = FakeClient({"arm_task_plan": PLAN, "arm_verdict": VERDICT})
    result = run_task("move the sponge", Session(), Cams(), ATLAS, client, {}, tmp_path)
    log = json.loads((tmp_path / (result["run_id"] + ".json")).read_bytes())
    assert [v["phase"] for v in log["verdicts"]] == ["grasp", "place"]
    assert all(v["source"] == "muse" for v in log["verdicts"])
