from dataclasses import asdict
import json
from pathlib import Path

import numpy as np
import pytest

from premonition import skills
from premonition.grasp_policy import ARMS, DEFAULT_PARAMS, HELP, GraspParams, make_chooser
from premonition.skills import GRIP_CLOSED_US, GRIP_OPEN_US, RELEASE_OPEN_US, grasp, grasp_target, in_contact, lifted, place, released


def test_save_memory_replaces_a_complete_snapshot_atomically(monkeypatch, tmp_path):
    path = tmp_path / skills.MEMORY_FILE
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"successes": 0, "attempts": []}')
    original = Path.replace
    snapshots = []

    def inspect_replace(source, target):
        if Path(target) == path:
            snapshots.append((json.loads(path.read_bytes()), json.loads(source.read_bytes())))
        return original(source, target)

    monkeypatch.setattr(Path, "replace", inspect_replace)
    memory = {"successes": 1, "attempts": [{"skill": "grasp", "class": "lifted"}]}
    skills.save_memory(tmp_path, memory)
    assert snapshots == [({"successes": 0, "attempts": []}, memory)]
    assert json.loads(path.read_bytes()) == memory


def test_grasp_raises_and_opens_before_the_approach(monkeypatch):
    session = Session()
    session.positions.update(shoulder=1400, gripper=1851)
    atlas = [{"pulses": {"base": 1650, "shoulder": 1640, "elbow": 2290}}]
    monkeypatch.setattr(skills, "observe", lambda cams: ({}, {"usb": obj(660), "c922": None}))
    seen = []

    def approach(arm, *args, **kwargs):
        seen.append(dict(arm.positions))
        return {"ok": False, "reason": "no_progress", "error_px": {}, "pulses": dict(arm.positions)}

    monkeypatch.setattr(skills, "reach", approach)
    grasp(session, None, atlas, {"grasp_offset_usb_x": 0, "attempts": []},
          choose=lambda tries: GraspParams(0, 90, 5, 1940, 2050), max_attempts=1)
    assert seen[0]["shoulder"] == 1640 and seen[0]["gripper"] == 1940
    shoulders = [1400] + [m["shoulder"] for m in session.log if "shoulder" in m]
    assert all(0 < b - a <= 60 for a, b in zip(shoulders, shoulders[1:]))


@pytest.mark.parametrize("current, reason, classification", [("pushed", "object_moved", "pushed"),
                                                          ("lost", "object_lost", "object_lost")])
def test_grasp_stops_without_retrying_when_approach_moves_or_loses_object(monkeypatch, current, reason, classification):
    session = Session()
    observations = iter([obj(660), obj(660), None if current == "lost" else obj(690, x1=740)])
    monkeypatch.setattr(skills, "observe", lambda cams: ({}, {"usb": next(observations), "c922": None}))
    called = []
    def approach(arm, *args, guard=None, **kwargs):
        called.append(True)
        assert callable(guard) and guard() == reason
        return {"ok": False, "reason": reason, "error_px": {}, "pulses": dict(arm.positions)}
    monkeypatch.setattr(skills, "reach", approach)
    memory = {"grasp_offset_usb_x": 0, "attempts": []}
    result = grasp(session, None, [], memory, choose=lambda tries: GraspParams())
    assert called == [True] and not result["ok"] and result["reason"] == f"approach_{reason}"
    assert len(memory["attempts"]) == 1 and memory["attempts"][0]["class"] == classification
    assert all(m.get("gripper") != GRIP_CLOSED_US for m in session.log)


def obj(top, cx=600, cy=None, x0=500, x1=700):
    return {"cx": cx, "cy": top + 90 if cy is None else cy, "top": top, "bottom": top + 180, "x0": x0, "x1": x1, "area": 30000}


def test_lifted_requires_usb_rise_and_c922_follow():
    before = {"c922": obj(780), "usb": obj(600)}
    assert lifted(before, {"c922": obj(768), "usb": obj(570)})
    assert not lifted(before, {"c922": obj(768), "usb": obj(580)})
    assert not lifted(before, {"c922": obj(777), "usb": obj(570)})


def test_lifted_accepts_a_sponge_pivoting_on_its_far_end():
    # 4 Nov round 9: held by one end, the sponge rose 21 px while the tip rose 42.4 px.
    before, after = {"usb": obj(700)}, {"usb": obj(679)}
    assert lifted(before, after, tip_rise=42.4)
    assert not lifted(before, {"usb": obj(692)}, tip_rise=42.4)
    # Round 10: held by a corner, the sponge rose 14 px while the tip rose only 19 px over the two steps.
    assert lifted(before, {"usb": obj(686)}, tip_rise=19.0)
    assert not lifted(before, {"usb": obj(695)}, tip_rise=19.0)


def test_lifted_accepts_missing_c922():
    assert lifted({"c922": obj(780), "usb": obj(600)}, {"c922": None, "usb": obj(570)})
    assert not lifted({"c922": obj(780), "usb": obj(600)}, {"c922": obj(760), "usb": None})


def test_released_detects_dragged_object():
    before = {"c922": obj(780), "usb": obj(600)}
    assert released(before, {"c922": obj(784), "usb": obj(605)})
    assert not released(before, {"c922": obj(784), "usb": obj(580)})


def test_released_accepts_a_sponge_that_drops_and_shifts_when_the_jaws_open():
    # 4 Nov round 11: let go a little above the table, the sponge fell onto the X and moved; the jaws left it there.
    before = {"c922": obj(780, x0=400, x1=700), "usb": obj(600)}
    assert released(before, {"c922": obj(800, x0=430, x1=730), "usb": obj(640, x0=530, x1=730)})


def test_approach_guard_ignores_a_box_that_grows_on_one_side(monkeypatch):
    # 4 Nov 17:40: sunlit table merged into the USB box, x1 850 -> 946 with x0 and top fixed; the sponge had not moved.
    session = Session()
    boxes = [obj(610, x0=600, x1=850), obj(610, x0=600, x1=850), obj(610, x0=600, x1=946), obj(612, x0=625, x1=975)]
    observations = iter(boxes + [boxes[-1]] * 20)
    monkeypatch.setattr(skills, "observe", lambda cams: ({}, {"usb": next(observations), "c922": None}))
    seen = []
    def approach(arm, *args, guard=None, **kwargs):
        seen.extend([guard(), guard()])
        return {"ok": False, "reason": "no_progress", "error_px": {}, "pulses": dict(arm.positions)}
    monkeypatch.setattr(skills, "reach", approach)
    grasp(session, None, [], {"grasp_offset_usb_x": 0, "attempts": []}, choose=lambda tries: GraspParams(), max_attempts=1)
    assert seen == [None, "object_moved"]


def test_released_reads_height_from_the_side_view():
    # 4 Nov: freed at 2090 the sponge straightened (front top +12 px, side -1); at 17:28 one still on the jaw rose 57/35 px.
    freed_before = {"c922": dict(obj(794), bottom=1075), "usb": dict(obj(644), bottom=895)}
    freed_after = {"c922": dict(obj(782), bottom=1074), "usb": dict(obj(645), bottom=896)}
    assert released(freed_before, freed_after)
    stuck_before = {"c922": dict(obj(852), bottom=1076), "usb": dict(obj(683), bottom=889)}
    stuck_after = {"c922": dict(obj(795), bottom=1075), "usb": dict(obj(648), bottom=883)}
    assert not released(stuck_before, stuck_after)


def test_release_opens_wider_than_any_grasp_opening():
    # At 1850 a sponge gripped from 1940 stayed wedged on the jaw; 2090 freed it (4 Nov 17:36).
    assert RELEASE_OPEN_US > max(arm.grip_open_us for arm in ARMS)


def test_in_contact_uses_half_of_tip_drop():
    assert in_contact(17, 35)
    assert not in_contact(30, 35)


def test_grasp_target_uses_outer_edge_and_memory_offset():
    target = grasp_target({"c922": obj(780, x0=400, x1=700), "usb": obj(600, x0=500)}, {"grasp_offset_usb_x": -10})
    assert target == {"usb": (505, 540), "c922": (490.0, None)}
    assert grasp_target({"c922": None, "usb": obj(600)}, {"grasp_offset_usb_x": 0})["c922"] is None


@pytest.mark.parametrize("opening", [1940, 1850])
def test_marked_jaw_target_centres_the_grip_and_keeps_true_tip_hover(monkeypatch, opening):
    from premonition import visual_servo
    monkeypatch.setattr(visual_servo, "MARKER_HSV", ((150, 35, 170), (173, 255, 255)))
    monkeypatch.setattr(visual_servo, "MARKER_JAW_DELTA", {"c922": [56, -36], "usb": [10, -4]}, raising=False)
    fraction = (opening - 1382) / (1940 - 1382)
    target = grasp_target({"c922": obj(780, x0=400, x1=700), "usb": obj(600, x0=500)},
                          {"grasp_offset_usb_x": -10, "grip_open_us": opening})
    assert target["c922"][0] == pytest.approx(490 + 56 * fraction)
    assert target["usb"][0] == pytest.approx(505 + 10 * fraction)
    assert target["usb"][1] == 540 and target["c922"][1] is None


class Session:
    def __init__(self):
        self.positions = {"base": 1450, "shoulder": 1560, "elbow": 2290, "wrist_pitch": 1182, "wrist_roll": 1567,
                          "gripper": GRIP_OPEN_US}
        self.log = []

    def move(self, targets, duration=None):
        self.positions.update(targets)
        self.log.append(dict(targets))

    def settle_move(self, targets, overshoot_us=20):
        self.move(targets)


class World:
    """Tip height follows the shoulder; the sponge rises with the tip only when the gripper closes on a good offset.
    A tip that lands on the sponge's top stays at blocked_at."""

    def __init__(self, monkeypatch, session, good_offset=None, table_tip_y=None, push_at=None, occlude_at=None,
                 blocked_at=None, reach_fails=0, hide_usb_tip_below=None, px_per_step=0.6):
        self.session, self.good_offset, self.table_tip_y, self.push_at = session, good_offset, table_tip_y, push_at
        self.occlude_at, self.blocked_at, self.reach_fails = occlude_at, blocked_at, reach_fails
        self.hide_usb_tip_below, self.px_per_step = hide_usb_tip_below, px_per_step
        self.held, self.offsets, self.top, self.calls = table_tip_y is not None, [], 600, []
        monkeypatch.setattr(skills, "observe", self.observe)
        monkeypatch.setattr(skills, "reach", self.reach)

    def tip_y(self):
        y = 500 + self.px_per_step * (1560 - self.session.positions["shoulder"])
        return y if self.blocked_at is None else min(y, self.blocked_at)

    def reach(self, session, cams, atlas, target, **kwargs):
        self.calls.append(({s["pulses"]["elbow"] for s in atlas}, kwargs))
        self.offsets.append(target["usb"][0] - (500 + 15))
        if self.reach_fails:
            self.reach_fails -= 1
            return {"ok": False, "reason": "diverging", "moves": 3, "error_px": {}, "pulses": session.positions, "seconds": 1}
        session.settle_move({"shoulder": 1560})
        return {"ok": True, "reason": "reached", "moves": 1, "error_px": {}, "pulses": session.positions, "seconds": 1}

    def observe(self, cams):
        closed = self.session.positions["gripper"] == GRIP_CLOSED_US
        if self.table_tip_y is not None:
            self.held = closed and self.held
            tip_y = self.tip_y()
            self.top = min(self.table_tip_y, tip_y) - 40 if self.held else self.top
        elif closed and self.offsets and self.offsets[-1] == self.good_offset:
            self.top = min(self.top, self.tip_y() - 40)
        tip = [600, self.tip_y()]
        pushed = self.push_at is not None and tip[1] > self.push_at
        hidden = self.occlude_at is not None and tip[1] > self.occlude_at
        found = (obj(self.top, cx=620, x1=720) if pushed else
                 dict(obj(self.top, cx=640, x0=540), bottom=self.top + 260) if hidden else obj(self.top))
        if self.hide_usb_tip_below is not None and tip[1] > self.hide_usb_tip_below:
            return {"c922": [700, tip[1]], "usb": None}, {"c922": None, "usb": found}
        return {"c922": None, "usb": tip}, {"c922": None, "usb": found}


def test_grasp_retries_with_offsets_then_asks_human(monkeypatch):
    session, memory = Session(), {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}
    world = World(monkeypatch, session)
    result = grasp(session, None, [], memory)
    assert world.offsets == [0, -15, 15]
    assert not result["ok"] and result["reason"] == "ask_human" and result["attempts"] == 3
    assert len(memory["attempts"]) == 3 and all("class" in a for a in memory["attempts"])
    assert [a["params"] for a in memory["attempts"]] == [asdict(GraspParams(o)) for o in (0, -15, 15)]
    assert result["tries"] == memory["attempts"] and result["help"] == HELP[memory["attempts"][-1]["class"]]
    assert session.positions["gripper"] == GRIP_OPEN_US


def test_grasp_takes_the_next_offset_from_advice_or_falls_back_to_the_local_sequence(monkeypatch):
    session, memory = Session(), {"grasp_offset_usb_x": 0, "successes": 0, "failures": []}
    world = World(monkeypatch, session)
    advice = iter([-30, None])
    result = grasp(session, None, [], memory, advise=lambda offset: next(advice))
    assert world.offsets == [0, -30, 15] and result["reason"] == "ask_human"


def shoulder_moves_before_each_close(session):
    runs, current = [], []
    for move in session.log:
        if move.get("gripper") == GRIP_CLOSED_US:
            runs.append(current)
        current = [] if move == {"shoulder": 1560} else current + [move["shoulder"]] if set(move) == {"shoulder"} else current
    return runs


def test_grasp_descent_stops_when_the_object_starts_to_move(monkeypatch):
    session = Session()
    World(monkeypatch, session, push_at=530)
    grasp(session, None, [], {"grasp_offset_usb_x": 0, "successes": 0, "failures": []})
    assert shoulder_moves_before_each_close(session)[0] == [1500]


def test_gripper_hiding_part_of_the_object_is_not_taken_for_a_push(monkeypatch):
    session = Session()
    World(monkeypatch, session, occlude_at=530)
    result = grasp(session, None, [], {"grasp_offset_usb_x": 0, "successes": 0, "failures": []})
    assert shoulder_moves_before_each_close(session)[0] == [1500, 1440, 1380]
    assert len(result["descents"][0]) == 3


def test_gripper_opens_wide_before_descending_in_steps_within_the_order_limit(monkeypatch):
    session = Session()
    session.positions["gripper"] = 1616
    World(monkeypatch, session)
    grasp(session, None, [], {"grasp_offset_usb_x": 0, "successes": 0, "failures": []})
    grips = [1616] + [m["gripper"] for m in session.log if "gripper" in m]
    assert GRIP_OPEN_US >= 1800 and grips[1] == GRIP_OPEN_US
    assert all(abs(a - b) <= 300 for a, b in zip(grips, grips[1:]))
    assert GRIP_CLOSED_US in grips


def test_grasp_descent_never_exceeds_three_steps(monkeypatch):
    session = Session()
    World(monkeypatch, session)
    grasp(session, None, [], {"grasp_offset_usb_x": 0, "successes": 0, "failures": []})
    assert shoulder_moves_before_each_close(session) == [[1500, 1440, 1380]] * 3


def test_grasp_lifts_and_learns_the_offset_that_worked(monkeypatch):
    session, memory = Session(), {"grasp_offset_usb_x": 0, "successes": 0, "failures": []}
    world = World(monkeypatch, session, good_offset=-15)
    result = grasp(session, None, [], memory)
    assert result["ok"] and result["attempts"] == 2 and world.offsets == [0, -15]
    assert memory["grasp_offset_usb_x"] == -15 and memory["successes"] == 1
    assert session.positions["gripper"] == GRIP_CLOSED_US
    assert result["pick_pulses"] == dict(session.positions, shoulder=session.positions["shoulder"] - 3 * 60)


def test_place_descends_until_contact_then_opens_and_checks_release(monkeypatch):
    session = Session()
    session.positions["gripper"] = GRIP_CLOSED_US
    World(monkeypatch, session, table_tip_y=600)
    result = place(session, None, [], {"usb": (515, 600), "c922": None}, {})
    assert result["ok"] and result["reason"] == "placed"
    assert session.positions["gripper"] == RELEASE_OPEN_US
    opened = next(i for i, m in enumerate(session.log) if m.get("gripper") == RELEASE_OPEN_US)
    assert [set(m) for m in session.log[opened + 1:]] == [{"shoulder"}] * 3


def test_place_climbs_to_clearance_after_judging_the_release(monkeypatch):
    # Muse read "still clamped" twice from photos taken three steps above a sponge that stayed on the table (4 Nov).
    session = Session()
    session.positions["gripper"] = GRIP_CLOSED_US
    World(monkeypatch, session, table_tip_y=600)
    atlas = [{"pulses": {"base": 1450, "shoulder": 1640, "elbow": 2170}, "tip": {}, "t": 0}]
    result = place(session, None, atlas, {"usb": (515, 600), "c922": None}, {})
    assert result["reason"] == "placed" and session.positions["shoulder"] == 1640


def test_grasp_and_place_servo_a_nearly_vertical_gripper_with_all_three_joints(monkeypatch):
    session, memory = Session(), {"grasp_offset_usb_x": 0, "successes": 0, "failures": []}
    world = World(monkeypatch, session, good_offset=0)
    atlas = [{"pulses": {"base": 1450, "shoulder": 1560, "elbow": e}, "tip": {}, "t": 0} for e in (2050, 2170, 2290)]
    grasp(session, None, atlas, memory)
    place(session, None, atlas, {"usb": (515, 600), "c922": None}, memory)
    assert callable(world.calls[0][1]["guard"]) and "guard" not in world.calls[1][1]
    assert [(elbows, {k: v for k, v in options.items() if k != "guard"}) for elbows, options in world.calls] == [
        ({2050, 2170, 2290}, {"joints": ("base", "shoulder", "elbow"), "tolerance": {"c922": 30, "usb": 25}})] * 2


def test_grasp_with_a_chooser_uses_its_params_for_every_part_of_the_attempt(monkeypatch):
    session = Session()
    session.positions["gripper"] = 1616
    world = World(monkeypatch, session)
    atlas = [{"pulses": {"base": 1450, "shoulder": 1560, "elbow": e}, "tip": {}, "t": 0} for e in (2050, 2170, 2290)]
    params = GraspParams(-30, 90, 5, 1940, 2170)
    result = grasp(session, None, atlas, {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []},
                   choose=lambda tries: params, max_attempts=1)
    grips = [1616] + [m["gripper"] for m in session.log if "gripper" in m]
    assert grips[:3] == [1616, 1916, 1940] and max(grips) == 1940
    assert all(abs(a - b) <= 300 for a, b in zip(grips, grips[1:]))
    assert shoulder_moves_before_each_close(session) == [[1500, 1440, 1380, 1320, 1260]]
    assert result["tries"][0]["descent_stop"] == "cap"
    assert [elbows for elbows, _ in world.calls] == [{2170, 2290}]
    assert world.offsets == [-30]


def test_grasp_with_a_chooser_lifts_back_above_a_long_descent_after_a_failure(monkeypatch):
    session, start = Session(), Session().positions["shoulder"]
    World(monkeypatch, session)
    seen = []

    def choose(tries):
        seen.append(session.positions["shoulder"])
        return GraspParams(0, 90, 5, 1940, 2050)
    result = grasp(session, None, [], {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}, choose=choose,
                   max_attempts=2)
    assert [t["descent_stop"] for t in result["tries"]] == ["cap", "cap"]
    assert [len(d) for d in result["descents"]] == [5, 5]
    assert all(s >= start for s in seen) and session.positions["shoulder"] >= start
    shoulders = [start] + [m["shoulder"] for m in session.log if "shoulder" in m]
    assert all(abs(b - a) <= 60 for a, b in zip(shoulders, shoulders[1:]))


def test_pushed_wins_over_reached_when_both_hold(monkeypatch):
    session = Session()
    World(monkeypatch, session, push_at=650)
    result = grasp(session, None, [], {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []},
                   choose=lambda tries: GraspParams(0, 60, 5, 1850, 2050), max_attempts=1)
    assert result["descents"][0][-1]["tip"][1] >= 600 + 60 and len(result["descents"][0]) == 5
    assert result["tries"][0]["descent_stop"] == "pushed" and result["tries"][0]["class"] == "pushed"


def test_place_records_placed_and_not_released_attempts(monkeypatch):
    memory = {"attempts": []}
    for lost_after_release in (False, True):
        session = Session()
        session.positions["gripper"] = GRIP_CLOSED_US
        world = World(monkeypatch, session, table_tip_y=600)
        if lost_after_release:
            def observe(cams, world=world, session=session):
                tips, objects = world.observe(cams)
                return tips, dict(objects, usb=None) if session.positions["gripper"] == RELEASE_OPEN_US else objects
            monkeypatch.setattr(skills, "observe", observe)
        place(session, None, [], {"usb": (515, 600), "c922": None}, memory)
    assert [(a["skill"], a["class"], a["legacy"]) for a in memory["attempts"]] == [
        ("place", "placed", False), ("place", "not_released", False)]
    assert all(isinstance(a["t"], float) for a in memory["attempts"])


def test_grasp_records_classified_attempts_with_their_params(monkeypatch):
    session, memory = Session(), {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}
    world = World(monkeypatch, session, good_offset=-15)
    first, second = GraspParams(0, 60, 4, 1850, 2050), GraspParams(-15, 60, 4, 1850, 2050)
    seen = []

    def choose(tries):
        seen.append(len(tries))
        return [first, second][len(tries)]
    result = grasp(session, None, [], memory, advise=lambda offset: offset - 30, choose=choose)
    assert result["ok"] and result["attempts"] == 2 and seen == [0, 1] and world.offsets == [0, -15]
    assert result["tries"] == memory["attempts"]
    assert [a["class"] for a in memory["attempts"]] == ["too_shallow", "lifted"]
    failed = memory["attempts"][0]
    assert failed["params"] == asdict(first) and memory["attempts"][1]["params"] == asdict(second)
    assert failed["skill"] == "grasp" and not failed["lifted"] and not failed["legacy"]
    assert failed["descent_stop"] == "cap" and failed["tip_end"][1] == pytest.approx(644)
    assert failed["resting"]["top"] == 600 and failed["after_lift"]["top"] == 600 and failed["rise_px"] == 0
    assert failed["muse_offset"] is None and memory["attempts"][1]["muse_offset"] is None
    assert memory["grasp_offset_usb_x"] == -15 and memory["successes"] == 1


def test_grasp_asks_for_help_after_three_attempts_of_the_same_class(monkeypatch):
    session, memory = Session(), {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}
    World(monkeypatch, session, blocked_at=560)
    result = grasp(session, None, [], memory, choose=make_chooser(memory, np.random.default_rng(0)), max_attempts=5)
    assert not result["ok"] and result["reason"] == "ask_human" and result["attempts"] == 3
    assert [a["class"] for a in result["tries"]] == ["jaws_on_top"] * 3 and result["help"] == HELP["jaws_on_top"]
    assert session.positions["gripper"] == GRIP_OPEN_US


def test_grasp_with_a_chooser_records_a_failed_reach_and_tries_other_params(monkeypatch):
    session, memory = Session(), {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}
    World(monkeypatch, session, good_offset=-15, reach_fails=1)
    first, second = GraspParams(0, 60, 4, 1850, 2050), GraspParams(-15, 60, 4, 1850, 2050)
    result = grasp(session, None, [], memory, choose=lambda tries: [first, second][len(tries)])
    assert result["ok"] and [t["class"] for t in result["tries"]] == ["reach_failed", "lifted"]
    failed = memory["attempts"][0]
    assert failed["reach"] == "diverging" and failed["params"] == asdict(first) and not failed["lifted"]
    assert failed["reach_error_px"] == {} and failed["reach_pulses"]["shoulder"] == 1560
    assert failed["seconds"] >= 0


def test_grasp_asks_for_help_after_three_failed_reaches(monkeypatch):
    session, memory = Session(), {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}
    World(monkeypatch, session, reach_fails=5)
    result = grasp(session, None, [], memory, choose=make_chooser(memory, np.random.default_rng(0)))
    assert result["reason"] == "ask_human" and result["attempts"] == 3 and result["help"] == HELP["reach_failed"]


def test_grasp_without_a_chooser_still_stops_at_the_first_failed_reach(monkeypatch):
    session, memory = Session(), {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}
    World(monkeypatch, session, reach_fails=1)
    assert grasp(session, None, [], memory)["reason"] == "reach_diverging" and memory["attempts"] == []


def test_descent_goes_on_while_a_jaw_hides_behind_the_sponge(monkeypatch):
    session, memory = Session(), {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}
    World(monkeypatch, session, hide_usb_tip_below=560)
    result = grasp(session, None, [], memory, choose=lambda tries: GraspParams(0, 90, 5, 1850, 2050), max_attempts=1)
    descent = result["descents"][0]
    assert len(descent) == 5 and descent[-1]["stop"] == "cap" and descent[-1]["tip"] is None


def test_descent_starts_when_the_open_jaws_already_hide_the_usb_tip(monkeypatch):
    session, memory = Session(), {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}
    World(monkeypatch, session, hide_usb_tip_below=490)
    result = grasp(session, None, [], memory, choose=lambda tries: GraspParams(0, 90, 5, 1850, 2050), max_attempts=1)
    assert len(result["descents"][0]) == 5 and result["descents"][0][-1]["stop"] == "cap"


def test_descent_is_lost_when_neither_camera_sees_the_tip(monkeypatch):
    session, memory = Session(), {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}
    world = World(monkeypatch, session)
    honest = world.observe
    monkeypatch.setattr(skills, "observe", lambda cams: (({"c922": None, "usb": None}, honest(cams)[1])
                                                         if session.positions["shoulder"] < 1500 else honest(cams)))
    result = grasp(session, None, [], memory, choose=lambda tries: GraspParams(0, 90, 5, 1850, 2050), max_attempts=1)
    assert result["descents"][0][-1]["stop"] == "lost"


def test_learning_grasp_judges_the_lift_over_two_steps_against_the_tip(monkeypatch):
    session, memory = Session(), {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}
    World(monkeypatch, session, good_offset=0, px_per_step=0.25)
    result = grasp(session, None, [], memory, choose=lambda tries: GraspParams(0, 60, 4, 1850, 2050), max_attempts=1)
    assert result["ok"] and result["tries"][0]["rise_px"] == pytest.approx(30)
    assert result["tries"][0]["tip_rise_px"] == pytest.approx(30)


def test_grasp_stops_at_once_when_the_object_is_lost(monkeypatch):
    session, memory = Session(), {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}
    world, advised = World(monkeypatch, session), []

    def observe(cams):
        tips, objects = world.observe(cams)
        return tips, dict(objects, usb=None) if session.positions["gripper"] == GRIP_CLOSED_US else objects
    monkeypatch.setattr(skills, "observe", observe)
    result = grasp(session, None, [], memory, advise=advised.append, choose=lambda tries: DEFAULT_PARAMS)
    assert result["reason"] == "ask_human" and result["attempts"] == 1 and result["help"] == HELP["object_lost"]
    assert [a["class"] for a in memory["attempts"]] == ["object_lost"] and advised == []
    assert session.positions["gripper"] == GRIP_OPEN_US


def test_grasp_with_a_chooser_asks_muse_only_after_a_not_lifted_attempt(monkeypatch):
    session, memory = Session(), {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}
    World(monkeypatch, session)
    classes, advised = iter(["not_lifted", "slipped", "slipped"]), []
    monkeypatch.setattr(skills, "classify", lambda record: next(classes))
    grasp(session, None, [], memory, advise=lambda offset: advised.append(offset) or -30,
          choose=lambda tries: DEFAULT_PARAMS, max_attempts=3)
    assert [a["class"] for a in memory["attempts"]] == ["not_lifted", "slipped", "slipped"]
    assert advised == [DEFAULT_PARAMS.offset_usb_x]
    assert [a["muse_offset"] for a in memory["attempts"]] == [-30, None, None]


def test_grasp_stops_on_the_time_limit(monkeypatch):
    session, clock = Session(), {"t": 0.0}
    World(monkeypatch, session)
    monkeypatch.setattr(skills.time, "perf_counter", lambda: clock["t"])

    def choose(tries):
        clock["t"] += 200
        return DEFAULT_PARAMS
    result = grasp(session, None, [], {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}, choose=choose)
    assert not result["ok"] and result["reason"] == "time_limit" and result["attempts"] == 2
    assert len(result["tries"]) == 2 and "help" not in result

def test_grasp_calls_photo_at_the_bottom_and_after_the_first_lift_without_changing_the_moves(monkeypatch):
    runs = []
    for photo in (None, "spy"):
        session, shots = Session(), []
        World(monkeypatch, session)
        spy = None if photo is None else lambda attempt, moment: shots.append((attempt, moment, len(session.log)))
        grasp(session, None, [], {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}, photo=spy)
        runs.append((session.log, shots))
    assert runs[0][0] == runs[1][0] and runs[0][1] == []
    assert [s[:2] for s in runs[1][1]] == [(1, "descent"), (1, "lift"), (2, "descent"), (2, "lift"),
                                           (3, "descent"), (3, "lift")]


def test_grasp_records_the_seconds_of_every_attempt(monkeypatch):
    session, clock = Session(), {"t": 0.0}
    World(monkeypatch, session)
    monkeypatch.setattr(skills.time, "perf_counter", lambda: clock["t"])
    move = session.move

    def timed_move(targets, duration=None):
        clock["t"] += 0.26
        move(targets, duration)
    session.move = timed_move
    memory = {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}
    grasp(session, None, [], memory, max_attempts=2)
    seconds = [a["seconds"] for a in memory["attempts"]]
    assert len(seconds) == 2
    assert seconds == [round(0.26 * len(session.log) / 2, 1)] * 2



def test_memory_round_trip(tmp_path):
    assert skills.load_memory(tmp_path) == {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}
    skills.save_memory(tmp_path, {"grasp_offset_usb_x": -15, "successes": 2,
                                  "failures": [{"t": 1.0, "reason": "not_lifted", "offset": -15}]})
    memory = skills.load_memory(tmp_path)
    assert memory["grasp_offset_usb_x"] == -15 and "failures" not in memory and memory["attempts"][0]["legacy"]
    assert (tmp_path / "real/calibration/skill_memory.json").exists()


@pytest.mark.parametrize("usb_rise, front_rise, expected", [(23, 26, True), (8, 26, False), (23, 8, False)])
def test_lifted_with_usb_tip_occluded_uses_front_geometry_and_side_motion(usb_rise, front_rise, expected):
    before = {"usb": obj(646), "c922": obj(748)}
    after = {"usb": obj(646 - usb_rise), "c922": obj(748 - front_rise)}
    assert lifted(before, after, tip_rise=None, front_tip_rise=43.8) is expected


def test_grasp_keeps_holding_when_the_side_tip_is_occluded_but_both_views_confirm_rise(monkeypatch):
    session, memory = Session(), {"grasp_offset_usb_x": 0, "successes": 0, "attempts": []}
    world = World(monkeypatch, session)
    anchor = []
    def observe(cams):
        if session.positions["gripper"] != GRIP_CLOSED_US:
            return world.observe(cams)
        if not anchor:
            anchor.append(session.positions["shoulder"])
        raised = session.positions["shoulder"] - anchor[0]
        return ({"usb": None, "c922": [748, 938.9 - 43.8 * raised / 120]},
                {"usb": obj(646 - 23 * raised / 120), "c922": obj(748 - 26 * raised / 120)})
    monkeypatch.setattr(skills, "observe", observe)
    result = grasp(session, None, [], memory, choose=lambda tries: GraspParams(0, 90, 5, 1940, 2050), max_attempts=1)
    assert result["ok"] and session.positions["gripper"] == GRIP_CLOSED_US
    assert memory["attempts"][0]["tip_rise_c922_px"] == pytest.approx(43.8)
    assert memory["attempts"][0]["class"] == "lifted"
