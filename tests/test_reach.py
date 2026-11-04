import numpy as np
import pytest

from premonition import reach as reach_module
from premonition.atlas import SCAN_GRID, serpentine
from premonition.reach import broyden, next_step, reach

JOINTS = ("base", "shoulder", "elbow")
A = np.array([[1.2, 0.3, -0.1], [0.4, -2.0, 0.6], [0.1, 0.36, -0.16], [-0.2, -0.64, 0.57]])
B = np.array([-1100.0, 2500.0, -200.0, 200.0])
PULSES = {"base": 1350, "shoulder": 1480, "elbow": 2170, "wrist_pitch": 1182, "wrist_roll": 1567, "gripper": 1382}


def true_tip(pulses):
    q = np.array([pulses[j] for j in JOINTS], float)
    bend = ((q - [1350, 1520, 2170]) / [200, 120, 120]) ** 2
    return A @ q + B + np.array([20, -15, 12, 10]) * bend.sum()


def test_error_leaves_a_free_coordinate_out():
    error, weights, px = reach_module._error({"c922": (100, None), "usb": (50, 60)}, {"c922": [90, 400], "usb": [50, 64]})
    assert error.tolist() == [10, 0, 0, -4] and weights.tolist() == [0.6, 0, 1.0, 1.0] and px == {"c922": 10.0, "usb": 4.0}


def test_next_step_reduces_weighted_error_within_cap():
    error = np.array([100.0, -50.0, 80.0, 40.0])
    step = next_step(A, error, np.ones(4), PULSES)
    dq = np.array([step[j] - PULSES[j] for j in JOINTS], float)
    assert max(abs(dq)) <= 150
    assert np.linalg.norm(error - A @ dq) < 0.9 * np.linalg.norm(error)


def test_next_step_respects_joint_limits():
    J = np.array([[0, 0, 0], [0, 0, 0], [1.0, 0, 0], [0, 0, 1.0]])
    step = next_step(J, np.array([0, 0, 100.0, 100.0]), np.ones(4), dict(PULSES, elbow=2290))
    assert step["elbow"] <= 2299 and step["base"] > PULSES["base"]
    assert next_step(J, np.array([0, 0, 100.0, 100.0]), np.ones(4), dict(PULSES, elbow=2250))["elbow"] == 2299


def test_next_step_returns_none_when_no_progress_possible():
    J = np.array([[0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 1.0]])
    assert next_step(J, np.array([0, 0, 0, 100.0]), np.ones(4), dict(PULSES, elbow=2299)) is None
    assert next_step(np.zeros((4, 3)), np.array([50.0, 50, 50, 50]), np.ones(4), PULSES) is None


def test_next_step_scales_a_tiny_step_up_to_the_minimum():
    J = np.array([[0, 0, 0], [0, 0, 0], [1.0, 0, 0], [0, 1.0, 0]])
    step = next_step(J, np.array([0, 0, 10.0, 6.0]), np.ones(4), PULSES)
    assert step == {"base": PULSES["base"] + 15, "shoulder": PULSES["shoulder"], "elbow": PULSES["elbow"]}


def test_next_step_stays_inside_the_given_bounds():
    J = np.array([[0, 0, 0], [0, 0, 0], [1.0, 0, 0], [0, 0, 0]])
    bounds = {"base": (1149, 1551), "shoulder": (1399, 1641), "elbow": (2049, 2291)}
    step = next_step(J, np.array([0, 0, -100.0, 0]), np.ones(4), dict(PULSES, base=1180), bounds=bounds)
    assert step["base"] == 1150


def test_broyden_matches_observed_motion():
    dq, dtip = np.array([40.0, -20.0, 10.0]), np.array([30.0, 12.0, -5.0, 9.0])
    assert np.allclose(broyden(A, dq, dtip) @ dq, dtip)
    partial = broyden(A, dq, np.array([np.nan, np.nan, -5.0, 9.0]))
    assert np.allclose(partial[:2], A[:2]) and np.allclose(partial[2:] @ dq, [-5.0, 9.0])


class Session:
    def __init__(self, positions):
        self.positions, self.moves = dict(positions), 0

    def move(self, targets, duration=None):
        self.positions.update(targets)
        self.moves += 1

    def settle_move(self, targets, overshoot_us=20):
        self.move(targets)


def simulated(monkeypatch, hide=(), c922_offset=(0, 0)):
    # The atlas holds only the 8 corners of the scan grid; between them the arm bends away from linear.
    atlas = []
    for pulses in serpentine(SCAN_GRID):
        if all(pulses[j] in (SCAN_GRID[j][0], SCAN_GRID[j][-1]) for j in JOINTS):
            tip = true_tip(pulses)
            atlas.append({"pulses": pulses, "t": 0.0, "tip": {"c922": tip[:2].tolist(), "usb": tip[2:].tolist()}})
    session = Session(PULSES)

    def look(cams):
        tip = true_tip(session.positions)
        return {"c922": None if "c922" in hide else (tip[:2] + c922_offset).tolist(),
                "usb": None if "usb" in hide else tip[2:].tolist()}
    monkeypatch.setattr(reach_module, "look", look)
    goal = true_tip({"base": 1420, "shoulder": 1540, "elbow": 2230})
    return session, atlas, {"c922": tuple(goal[:2]), "usb": tuple(goal[2:])}


def test_reach_converges_on_simulated_arm_in_few_moves(monkeypatch):
    session, atlas, target = simulated(monkeypatch)
    start = reach_module.nearest_sample(atlas, target)["pulses"]
    assert np.linalg.norm(true_tip(dict(PULSES, **start)) - np.r_[target["c922"], target["usb"]]) > 200
    result = reach(session, None, atlas, target)
    assert result["ok"] and result["reason"] == "reached" and 2 <= result["moves"] <= 6
    assert result["error_px"]["usb"] <= 15 and result["error_px"]["c922"] <= 30
    assert session.positions["gripper"] == PULSES["gripper"]
    assert len(result["trace"]) == result["moves"] + 1 and result["trace"][0]["step"] is not None


def test_reach_ignores_c922_when_its_tip_is_missing(monkeypatch):
    session, atlas, target = simulated(monkeypatch, hide=("c922",))
    result = reach(session, None, atlas, target)
    assert result["ok"] and result["error_px"]["c922"] is None and result["error_px"]["usb"] <= 15


def test_reach_drops_a_c922_tip_that_contradicts_the_atlas(monkeypatch):
    session, atlas, target = simulated(monkeypatch, c922_offset=(330, -280))
    result = reach(session, None, atlas, target)
    assert result["ok"] and result["error_px"]["c922"] is None and result["error_px"]["usb"] <= 15


def test_reach_rechecks_one_jumped_frame_before_calling_it_diverging(monkeypatch):
    session, atlas, target = simulated(monkeypatch)
    honest, calls = reach_module.look, []

    def look(cams):
        calls.append(1)
        tip = honest(cams)
        return dict(tip, usb=[tip["usb"][0] + 400, tip["usb"][1]]) if len(calls) == 2 else tip
    monkeypatch.setattr(reach_module, "look", look)
    assert reach(session, None, atlas, target)["ok"]


def test_reach_never_leaves_the_scanned_pulse_box(monkeypatch):
    session, atlas, _ = simulated(monkeypatch)
    goal = true_tip({"base": 1000 + 60, "shoulder": 1520, "elbow": 2230})
    result = reach(session, None, atlas, {"c922": tuple(goal[:2]), "usb": tuple(goal[2:])})
    assert not result["ok"] and session.positions["base"] >= 1150


def test_reach_starts_from_a_sample_above_the_target(monkeypatch):
    below = {"pulses": {"base": 1450, "shoulder": 1400, "elbow": 2170}, "t": 0, "tip": {"c922": None, "usb": [530, 590]}}
    above = {"pulses": {"base": 1450, "shoulder": 1560, "elbow": 2170}, "t": 0, "tip": {"c922": None, "usb": [540, 480]}}
    session = Session(PULSES)
    monkeypatch.setattr(reach_module, "look", lambda cams: {"c922": None, "usb": [536, 548]})
    assert reach(session, None, [below, above], {"c922": None, "usb": (536, 548)})["ok"]
    assert session.positions["shoulder"] == 1560


def test_reach_can_servo_base_and_shoulder_only(monkeypatch):
    session, atlas, _ = simulated(monkeypatch)
    vertical = [s for s in atlas if s["pulses"]["elbow"] == 2290]
    goal = true_tip({"base": 1420, "shoulder": 1540, "elbow": 2290})
    result = reach(session, None, vertical, {"c922": tuple(goal[:2]), "usb": tuple(goal[2:])}, joints=("base", "shoulder"))
    assert result["ok"] and session.positions["elbow"] == 2290


def test_reach_stops_when_usb_tip_is_lost(monkeypatch):
    session, atlas, target = simulated(monkeypatch, hide=("usb",))
    result = reach(session, None, atlas, target)
    assert not result["ok"] and result["reason"] == "usb_tip_lost" and result["moves"] == 0
