import json

import cv2
import numpy as np
import pytest

from premonition import visual_servo
from premonition.arm_session import OVERSHOOT_US
from premonition.atlas import (SCAN_GRID, backlash_us, detector_report, local_jacobian, locate_tips, look, merge_scans, nearest_sample,
                               predict_tip, scan, serpentine, stalled, travel)
from premonition.dual_camera import Frame
from premonition.visual_servo import BASE_PX

JOINTS = ("base", "shoulder", "elbow")
A = np.array([[1.2, 0.3, -0.1], [0.4, -2.0, 0.6], [0.1, 0.36, -0.16], [-0.2, -0.64, 0.57]])
B = np.array([100.0, 900.0, 300.0, 1500.0])


def linear_samples(drop_c922=()):
    samples = []
    for i, pulses in enumerate(serpentine(SCAN_GRID)):
        tip = A @ np.array([pulses[j] for j in JOINTS], float) - B
        samples.append({"pulses": pulses, "t": float(i),
                        "tip": {"c922": None if i in drop_c922 else tip[:2].tolist(), "usb": tip[2:].tolist()}})
    return samples


def test_serpentine_visits_every_grid_pose_once():
    poses = serpentine(SCAN_GRID)
    assert len(poses) == 60 and len({tuple(p.values()) for p in poses}) == 60


def test_serpentine_never_jumps_more_than_one_grid_step_per_joint():
    poses = serpentine(SCAN_GRID)
    for a, b in zip(poses, poses[1:]):
        for joint in JOINTS:
            assert abs(SCAN_GRID[joint].index(a[joint]) - SCAN_GRID[joint].index(b[joint])) <= 1


def test_serpentine_changes_base_only_with_shoulder_at_its_highest_value():
    poses = serpentine(SCAN_GRID)
    assert poses[0]["shoulder"] == SCAN_GRID["shoulder"][0]
    for a, b in zip(poses, poses[1:]):
        if a["base"] != b["base"]:
            assert a["shoulder"] == b["shoulder"] == SCAN_GRID["shoulder"][0]


def test_stalled_needs_both_views_still_for_a_real_step():
    before = {"c922": [500, 500], "usb": [600, 400]}
    still = {"c922": [502, 501], "usb": [601, 403]}
    assert stalled(before, still, 40)
    assert not stalled(before, still, 10)
    assert not stalled(before, {"c922": [506, 500], "usb": [601, 403]}, 40)


def test_local_jacobian_recovers_a_linear_camera_model():
    J = local_jacobian(linear_samples(), {"base": 1350, "shoulder": 1480, "elbow": 2170})
    assert J.shape == (4, 3) and np.allclose(J, A, atol=1e-6)


def test_local_jacobian_skips_missing_c922_rows():
    samples = linear_samples(drop_c922=set(range(0, 60, 2)))
    J = local_jacobian(samples, {"base": 1350, "shoulder": 1480, "elbow": 2170})
    assert np.allclose(J, A, atol=1e-6)


def test_nearest_sample_weights_usb_over_c922():
    near_c922 = {"pulses": {"base": 1}, "t": 0, "tip": {"c922": [100, 100], "usb": [150, 100]}}
    near_usb = {"pulses": {"base": 2}, "t": 0, "tip": {"c922": [150, 100], "usb": [100, 100]}}
    target = {"c922": (100, 100), "usb": (100, 100)}
    assert nearest_sample([near_c922, near_usb], target) is near_usb
    assert nearest_sample([near_c922, near_usb], dict(target, usb=None)) is near_c922


def test_nearest_sample_leaves_a_free_coordinate_out():
    low = {"pulses": {"base": 1}, "t": 0, "tip": {"c922": [100, 900], "usb": [0, 0]}}
    high = {"pulses": {"base": 2}, "t": 0, "tip": {"c922": [400, 100], "usb": [0, 0]}}
    assert nearest_sample([high, low], {"c922": (100, None), "usb": (0, 0)}) is low


def test_nearest_sample_does_not_favour_samples_missing_a_view():
    one_view = {"pulses": {"base": 1}, "t": 0, "tip": {"c922": None, "usb": [140, 100]}}
    both = {"pulses": {"base": 2}, "t": 0, "tip": {"c922": [130, 100], "usb": [130, 100]}}
    assert nearest_sample([one_view, both], {"c922": (100, 100), "usb": (100, 100)}) is both


def test_predict_tip_uses_the_nearest_sample_that_has_the_view():
    samples = linear_samples()
    centre = next(s for s in samples if s["pulses"] == {"base": 1350, "shoulder": 1480, "elbow": 2170})
    centre["tip"]["c922"] = None
    assert predict_tip(samples, centre["pulses"])["c922"] is not None


class Session:
    def __init__(self, positions):
        self.positions, self.moves = dict(positions), []

    def move(self, targets, duration=None):
        self.positions.update(targets)
        self.moves.append(dict(self.positions))

    def settle_move(self, targets, overshoot_us=20):
        self.move(targets)


def test_travel_splits_long_jumps_and_raises_shoulder_first():
    session = Session({"base": 1499, "shoulder": 1500, "elbow": 2290})
    travel(session, {"base": 1150, "shoulder": 1640, "elbow": 2050})
    assert session.moves[0] == {"base": 1499, "shoulder": 1640, "elbow": 2290}
    assert session.positions == {"base": 1150, "shoulder": 1640, "elbow": 2050}
    for a, b in zip([{"base": 1499, "shoulder": 1500, "elbow": 2290}] + session.moves, session.moves):
        assert max(abs(a[j] - b[j]) for j in a) <= 280


def test_travel_lowers_shoulder_last():
    session = Session({"base": 1150, "shoulder": 1640, "elbow": 2050})
    travel(session, {"base": 1450, "shoulder": 1400, "elbow": 2290})
    assert [m["shoulder"] for m in session.moves[:-1]] == [1640] * (len(session.moves) - 1)
    assert session.positions == {"base": 1450, "shoulder": 1400, "elbow": 2290}


def test_travel_cap_leaves_room_for_the_largest_overshoot(monkeypatch):
    monkeypatch.setitem(OVERSHOOT_US, "elbow", 60)
    start = {"base": 1499, "shoulder": 1500, "elbow": 2290}
    session = Session(start)
    travel(session, {"base": 1150, "shoulder": 1500, "elbow": 2290})
    assert session.positions["base"] == 1150
    assert max(abs(a["base"] - b["base"]) for a, b in zip([start] + session.moves, session.moves)) == 240


def test_backlash_us_divides_by_the_usb_sensitivity():
    assert backlash_us(6.0, np.array([3.0, 4.0])) == 1.2


def test_look_retakes_the_snapshot_when_the_usb_tip_is_missed(monkeypatch):
    monkeypatch.setattr(visual_servo, "MARKER_HSV", None)
    blank = np.full((1080, 1920, 3), (150, 140, 135), np.uint8)
    drawn = blank.copy()
    cv2.line(drawn, BASE_PX["usb"], (600, 400), (230, 120, 30), 40)
    shots = iter([blank, drawn])

    class Cams:
        def snapshot(self, after=None, timeout=5.0):
            return {"c922": Frame(0.0, blank, b""), "usb": Frame(0.0, next(shots), b"")}
    tips = look(Cams())
    assert tips["c922"] is None and abs(tips["usb"][0] - 600) < 25 and abs(tips["usb"][1] - 400) < 25


def test_predict_tip_extrapolates_from_the_nearest_sample():
    pose = {"base": 1467, "shoulder": 1500, "elbow": 2200}
    expected = A @ np.array([pose[j] for j in JOINTS], float) - B
    predicted = predict_tip(linear_samples(), pose)
    assert np.allclose(predicted["c922"], expected[:2]) and np.allclose(predicted["usb"], expected[2:])


def test_merge_scans_averages_agreeing_views_and_drops_disagreeing_ones():
    pulses = {"base": 1150, "shoulder": 1640, "elbow": 2050}
    first = [{"pulses": pulses, "t": 0.0, "tip": {"c922": [100, 100], "usb": [500, 500]}},
             {"pulses": dict(pulses, elbow=2170), "t": 0.0, "tip": {"c922": None, "usb": [300, 300]}}]
    second = [{"pulses": pulses, "t": 1.0, "tip": {"c922": [110, 100], "usb": [580, 500]}},
              {"pulses": dict(pulses, elbow=2170), "t": 1.0, "tip": {"c922": [50, 60], "usb": [304, 300]}}]
    merged = merge_scans(first, second)
    assert merged[0]["tip"] == {"c922": [105.0, 100.0], "usb": None}
    assert merged[1]["tip"] == {"c922": [50, 60], "usb": [302.0, 300.0]}


def test_marker_detector_is_off_until_configured_in_locate_tips(monkeypatch):
    monkeypatch.setattr(visual_servo, "MARKER_HSV", None)
    image = np.full((1080, 1920, 3), (150, 140, 135), np.uint8)
    cv2.line(image, BASE_PX["usb"], (600, 400), (230, 120, 30), 40)
    cv2.ellipse(image, (600, 400), (22, 14), 0, 0, 360, (200, 0, 200), -1)
    frames = {"c922": Frame(0.0, image, b""), "usb": Frame(0.0, image, b"")}
    expected = {view: visual_servo.locate_tip(image, BASE_PX[view]) for view in frames}
    tips = locate_tips(frames)
    for view in frames:
        assert (tips[view] is None) == (expected[view] is None)
        if tips[view] is not None:
            assert np.allclose(tips[view], expected[view], atol=0.1)


def test_scan_saves_both_stream_frames_and_the_blue_tip(tmp_path, monkeypatch):
    monkeypatch.setattr(visual_servo, "MARKER_HSV", None)
    images = {view: np.full((1080, 1920, 3), (150, 140, 135), np.uint8) for view in BASE_PX}
    cv2.line(images["usb"], BASE_PX["usb"], (600, 400), (230, 120, 30), 40)
    cv2.line(images["c922"], BASE_PX["c922"], (700, 400), (230, 120, 30), 40)

    class Cams:
        def snapshot(self, after=None, timeout=5.0):
            return {view: Frame(0.0, images[view], b"jpeg-" + view.encode()) for view in images}
    grid = {"base": [1450], "shoulder": [1400], "elbow": [2170]}
    session = Session({"base": 1450, "shoulder": 1400, "elbow": 2170})
    frames_dir = tmp_path / "frames"
    report = scan(session, Cams(), grid, tmp_path / "out.json", frames_dir)
    assert "marker_hsv" in report and report["marker_hsv"] is None
    assert report["overshoot_us"]["shoulder"] == 60
    assert (frames_dir / "000_c922.jpg").read_bytes() == b"jpeg-c922"
    assert (frames_dir / "000_usb.jpg").read_bytes() == b"jpeg-usb"
    blue = report["atlas"][0]["tip_blue"]
    assert abs(blue["usb"][0] - 600) < 25 and abs(blue["c922"][0] - 700) < 25
    assert blue == report["atlas"][0]["tip"] and blue is not report["atlas"][0]["tip"]
    assert json.loads((tmp_path / "out.json").read_text())["atlas"][0]["tip_blue"] == blue
    scan(session, Cams(), grid, tmp_path / "again.json")
    assert sorted(p.name for p in tmp_path.rglob("*.jpg")) == ["000_c922.jpg", "000_usb.jpg"]


def test_merge_scans_keeps_the_blue_tip():
    pulses = {"base": 1150, "shoulder": 1640, "elbow": 2050}
    first = [{"pulses": pulses, "t": 0.0, "tip": {"c922": [1, 1], "usb": [2, 2]}, "tip_blue": {"c922": [9, 9], "usb": None}}]
    second = [{"pulses": pulses, "t": 1.0, "tip": {"c922": [1, 1], "usb": [2, 2]}, "tip_blue": {"c922": [5, 5], "usb": [6, 6]}}]
    assert merge_scans(first, second)[0]["tip_blue"] == {"c922": [5, 5], "usb": [6, 6]}


def test_detector_report_counts_disagreements_per_detector():
    pulses = {"base": 1150, "shoulder": 1640, "elbow": 2050}

    def sample(tip, blue):
        return {"pulses": pulses, "t": 0.0, "tip": tip, "tip_blue": blue}
    first = [sample({"c922": [100, 100], "usb": [500, 500]}, {"c922": [100, 100], "usb": [500, 500]}),
             sample({"c922": [100, 100], "usb": None}, {"c922": [100, 104], "usb": [300, 300]})]
    second = [sample({"c922": [100, 130], "usb": [503, 500]}, {"c922": [100, 103], "usb": [500, 540]}),
              sample({"c922": None, "usb": [300, 306]}, {"c922": [100, 100], "usb": [300, 300]})]
    report = detector_report(first, second)
    assert report["c922"] == {"visible": 0.75, "jumps_tip": 1, "jumps_blue": 0, "median_tip_vs_blue_px": 4.0}
    assert report["usb"] == {"visible": 0.75, "jumps_tip": 0, "jumps_blue": 1, "median_tip_vs_blue_px": 6.0}


def test_atlas_restores_its_own_tip_detector(monkeypatch):
    from premonition import atlas
    monkeypatch.setattr(visual_servo, "MARKER_HSV", None)
    monkeypatch.setattr(visual_servo, "MARKER_POINT", "centroid", raising=False)
    monkeypatch.setattr(visual_servo, "MARKER_ROIS", {}, raising=False)
    bounds = [[150, 50, 180], [173, 255, 255]]
    rois = {"c922": [420, 100, 1150, 1060], "usb": [450, 100, 1000, 850]}
    atlas.configure_tip_detector({"marker_hsv": bounds, "marker_point": "lower_edge", "marker_rois": rois})
    assert visual_servo.MARKER_HSV == tuple(tuple(row) for row in bounds)
    assert visual_servo.MARKER_POINT == "lower_edge"
    assert visual_servo.MARKER_ROIS == rois
    atlas.configure_tip_detector({})
    assert visual_servo.MARKER_HSV is None
    assert visual_servo.MARKER_POINT == "centroid"
    assert visual_servo.MARKER_ROIS == {}


@pytest.mark.parametrize("rois", [{"unknown": [0, 0, 100, 100]}, {"usb": [-1, 0, 100, 100]},
    {"usb": [0, 0, 1921, 100]}, {"usb": [100, 100, 10, 10]}, {"usb": [0, 0, 100]}])
def test_atlas_rejects_an_invalid_marker_workspace(monkeypatch, rois):
    from premonition import atlas
    monkeypatch.setattr(visual_servo, "MARKER_HSV", None)
    with pytest.raises(ValueError, match="marker_rois"):
        atlas.configure_tip_detector({"marker_hsv": [[150, 50, 180], [173, 255, 255]], "marker_rois": rois})


@pytest.mark.parametrize("point", ["unknown", 1, None])
def test_atlas_rejects_an_unknown_marker_point(monkeypatch, point):
    from premonition import atlas
    monkeypatch.setattr(visual_servo, "MARKER_HSV", None)
    with pytest.raises(ValueError, match="marker_point"):
        atlas.configure_tip_detector({"marker_hsv": [[150, 50, 180], [173, 255, 255]], "marker_point": point})


@pytest.mark.parametrize("bounds", [[], [[150, 50], [173, 255, 255]],
    [[180, 50, 180], [173, 255, 255]], [[150, -1, 180], [173, 255, 255]],
    [[150, 50, 180], [173, 256, 255]], [[True, 50, 180], [173, 255, 255]]])
def test_invalid_atlas_marker_configuration_stops_before_using_it(monkeypatch, bounds):
    from premonition import atlas
    monkeypatch.setattr(visual_servo, "MARKER_HSV", None)
    with pytest.raises(ValueError, match="marker_hsv"):
        atlas.configure_tip_detector({"marker_hsv": bounds})
    assert visual_servo.MARKER_HSV is None


def jaw_geometry(monkeypatch):
    monkeypatch.setattr(visual_servo, "MARKER_HSV", ((150, 35, 170), (173, 255, 255)))
    monkeypatch.setattr(visual_servo, "MARKER_JAW_DELTA", {"c922": [56, -36], "usb": [10, -4]}, raising=False)
    monkeypatch.setattr(visual_servo, "MARKER_ATLAS_GRIPPER_US", 1940, raising=False)


def test_prediction_follows_the_marked_jaw_when_it_closes(monkeypatch):
    jaw_geometry(monkeypatch)
    atlas = linear_samples()
    pose = {"base": 1450, "shoulder": 1480, "elbow": 2170}
    opened = predict_tip(atlas, dict(pose, gripper=1940))
    closed = predict_tip(atlas, dict(pose, gripper=1382))
    assert np.allclose(np.subtract(closed["c922"], opened["c922"]), [-56, 36])
    assert np.allclose(np.subtract(closed["usb"], opened["usb"]), [-10, 4])


def test_referenced_atlas_aperture_never_applies_the_shift_twice(monkeypatch):
    from premonition import atlas as module
    jaw_geometry(monkeypatch)
    samples = linear_samples()
    before = json.loads(json.dumps(samples))
    shifted = module.at_gripper(samples, 1382)
    pose = dict(samples[3]["pulses"], gripper=1382)
    assert samples == before
    assert all(s["pulses"]["gripper"] == 1382 for s in shifted)
    for view in ("c922", "usb"):
        assert np.allclose(predict_tip(shifted, pose)[view], predict_tip(samples, pose)[view])


@pytest.mark.parametrize("delta", [{"usb": [10, 4]}, {"c922": [float("nan"), 1], "usb": [1, 2]},
    {"c922": [201, 1], "usb": [1, 2]}, {"c922": [1], "usb": [1, 2]}])
def test_atlas_rejects_invalid_jaw_displacement(monkeypatch, delta):
    from premonition import atlas as module
    monkeypatch.setattr(visual_servo, "MARKER_HSV", None)
    with pytest.raises(ValueError, match="jaw_open_minus_closed_px"):
        module.configure_tip_detector({"marker_hsv": [[150, 35, 170], [173, 255, 255]], "jaw_open_minus_closed_px": delta})
