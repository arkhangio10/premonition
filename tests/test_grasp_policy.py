from dataclasses import asdict

import numpy as np
import pytest

from premonition import skills
from premonition.grasp_policy import (ARMS, DEFAULT_PARAMS, HELP, TOWARD, GraspParams, classify,
                                      make_chooser, posterior, upgrade_memory)

BOX = {"cx": 960, "cy": 600, "top": 500, "bottom": 700, "x0": 900, "x1": 1020, "area": 9000}
LOST = {**BOX, "top": 600}


def attempt(**kw):
    base = {"skill": "grasp", "params": asdict(DEFAULT_PARAMS), "class": "not_lifted", "lifted": False,
            "descent_stop": "reached", "tip_end": [900, 600], "resting": BOX, "after_lift": BOX,
            "rise_px": 12.0, "muse_offset": None, "legacy": False}
    return {**base, **kw}


def test_default_params_reproduce_the_current_grasp():
    assert DEFAULT_PARAMS == GraspParams(0, 60, 3, 1850, 2050)
    assert DEFAULT_PARAMS.grip_open_us == skills.GRIP_OPEN_US
    assert DEFAULT_PARAMS.max_steps == skills.MAX_DESCENT_STEPS
    assert DEFAULT_PARAMS.elbow_min_us == skills.GRASP_ELBOW_MIN_US


def test_arms_stay_strictly_inside_the_limits():
    assert len(ARMS) == 20 and len(set(ARMS)) == 20
    assert {arm.offset_usb_x for arm in ARMS} == {30, 15, 0, -15, -30}
    for arm in ARMS:
        assert 1130 < arm.grip_open_us < 1950 and 1000 < arm.elbow_min_us < 2300
        assert arm.max_steps <= 5 and arm.max_steps * 60 <= 300


@pytest.mark.parametrize("kw, expected", [
    ({"lifted": True}, "lifted"),
    ({"descent_stop": "pushed"}, "pushed"),
    ({"after_lift": None}, "object_lost"),
    ({"after_lift": LOST}, "object_lost"),
    ({"after_lift": None, "after_lift_c922": BOX}, "not_lifted"),
    ({"after_lift": LOST, "after_lift_c922": BOX}, "not_lifted"),
    ({"descent_stop": "stalled", "tip_end": [900, 520]}, "jaws_on_top"),
    ({"descent_stop": "cap", "tip_end": [900, 540]}, "too_shallow"),
    ({"rise_px": 12.0}, "slipped"),
    ({"rise_px": 2.0, "tip_end": [900, 600]}, "closed_on_air"),
    ({"rise_px": 40.0}, "not_lifted"),
    ({"rise_px": None, "tip_end": None}, "not_lifted"),
    ({"descent_stop": "stalled", "tip_end": None, "rise_px": 40.0}, "not_lifted"),
])
def test_classify_follows_the_table(kw, expected):
    assert classify(attempt(**kw)) == expected


def test_every_failure_class_has_help_text():
    for cls in ("pushed", "object_lost", "jaws_on_top", "too_shallow", "slipped", "closed_on_air", "not_lifted"):
        assert HELP[cls]
    assert set(TOWARD) == {"jaws_on_top", "pushed", "closed_on_air", "too_shallow", "slipped"}


def test_chooser_moves_outward_after_jaws_on_top():
    last = attempt(params=asdict(GraspParams(-15, 60, 4, 1850, 2050)), **{"class": "jaws_on_top"})
    for seed in range(50):
        pick = make_chooser({"attempts": []}, np.random.default_rng(seed))([last])
        assert pick.offset_usb_x < -15 or pick.grip_open_us > 1850


def test_chooser_prefers_an_arm_that_already_lifted():
    best = GraspParams(-30, 90, 5, 1940, 2170)
    attempts = [attempt(params=asdict(best), lifted=True, **{"class": "lifted"}) for _ in range(2)]
    attempts += [attempt(params=asdict(a)) for a in ARMS if a != best]
    wins = [make_chooser({"attempts": attempts}, np.random.default_rng(s))([]) for s in range(200)]
    counts = {a: wins.count(a) for a in ARMS}
    assert max(counts, key=counts.get) == best
    assert counts[best] >= 80


def test_chooser_uses_muse_offset_only_when_the_local_class_is_unknown():
    params = asdict(GraspParams(-15, 60, 4, 1850, 2050))
    for seed in range(30):
        rng = np.random.default_rng(seed)
        unknown = attempt(params=params, muse_offset=-30)
        assert make_chooser({"attempts": []}, rng)([unknown]).offset_usb_x < -15
        known = attempt(params=params, muse_offset=-30, **{"class": "closed_on_air"})
        assert make_chooser({"attempts": []}, rng)([known]).offset_usb_x > -15


def test_chooser_never_repeats_the_last_arm_within_a_call():
    for seed in range(50):
        rng = np.random.default_rng(seed)
        last = ARMS[seed % 12]
        pick = make_chooser({"attempts": []}, rng)([attempt(params=asdict(last), **{"class": "lifted"})])
        assert pick != last


def test_legacy_failures_are_kept_but_not_counted():
    memory = {"grasp_offset_usb_x": 0, "successes": 0,
              "failures": [{"t": 1.0 + i, "reason": "not_lifted", "offset": 0} for i in range(8)]}
    upgraded = upgrade_memory(memory)
    assert "failures" not in upgraded and len(upgraded["attempts"]) == 8
    assert all(a["legacy"] and a["class"] == "unclassified" for a in upgraded["attempts"])
    assert posterior(upgraded["attempts"], GraspParams(0, 60, 4, 1850, 2050)) == (1, 1)


def test_repeat_success_uses_the_learned_profile_first_then_resumes_learning():
    best = GraspParams(0, 90, 5, 1940, 2050)
    memory = {"attempts": [attempt(params=asdict(best), lifted=True, **{"class": "lifted"})]}
    for seed in range(20):
        choose = make_chooser(memory, np.random.default_rng(seed), repeat_success=True)
        assert choose([]) == best
        failed = attempt(params=asdict(best), **{"class": "pushed"})
        following = choose([failed])
        assert following != best and following.offset_usb_x < 0


def test_repeat_success_ignores_legacy_place_and_out_of_range_profiles():
    history = [attempt(params=asdict(ARMS[0]), lifted=True, legacy=True),
               attempt(params=asdict(ARMS[1]), lifted=True, skill="place"),
               attempt(params=asdict(GraspParams(0, 90, 5, 1950, 2050)), lifted=True)]
    memory = {"attempts": history}
    expected = make_chooser(memory, np.random.default_rng(3))([])
    assert make_chooser(memory, np.random.default_rng(3), repeat_success=True)([]) == expected
