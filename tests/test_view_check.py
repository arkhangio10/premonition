import math

import cv2
import numpy as np
import pytest

from premonition.atlas import SCAN_GRID, predict_tip, serpentine
from premonition.dual_camera import Frame
from premonition.view_check import (TEST_POINTS, agreement, apply, check_views, decide, next_action, save_reference,
                                    shift_atlas, view_shift)
from premonition.visual_servo import BASE_PX

ORIGIN = np.array([[1, 0, -240], [0, 1, -210]], float)
BLUE = (140, 109, 40)
ARM = np.array([(0, 0), (60, -30), (380, -330), (640, -200), (600, -150), (370, -250), (70, 50)])


def world(arm_at=(900, 1000), marker=False):
    """A scene bigger than one view: softly shaded wall and table, a few boxes, the blue arm and maybe the ArUco.

    Like the real wall, the shading carries little texture, so an unmasked arm would pull the alignment."""
    noise = np.random.default_rng(0).integers(0, 256, (1500, 2400), dtype=np.uint8)
    gray = cv2.normalize(cv2.GaussianBlur(noise, (0, 0), 15), None, 150, 200, cv2.NORM_MINMAX)
    image = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    for x, y, w, h, shade in ((500, 400, 300, 180, 245), (1500, 300, 220, 400, 25), (1700, 1000, 380, 150, 200)):
        cv2.rectangle(image, (x, y), (x + w, y + h), (shade,) * 3, -1)
    if marker:
        cv2.rectangle(image, (450, 900), (710, 1160), (255, 255, 255), -1)
        tag = cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), 0, 180)
        image[940:1120, 490:670] = cv2.cvtColor(tag, cv2.COLOR_GRAY2BGR)
    cv2.fillPoly(image, [ARM + arm_at], BLUE)
    return image


def motion(dx, dy, degrees=0.0):
    matrix = cv2.getRotationMatrix2D((960, 540), degrees, 1.0)
    matrix[:, 2] += (dx, dy)
    return matrix


def camera(scene, moved=None):
    """What a 1920x1080 camera sees of the table, after it moved by `moved` (in its own pixels).

    The blur stands for the softness of a 1280x720 stream upscaled to 1920x1080."""
    matrix = ORIGIN if moved is None else (np.vstack([moved, (0, 0, 1)]) @ np.vstack([ORIGIN, (0, 0, 1)]))[:2]
    return cv2.GaussianBlur(cv2.warpAffine(scene, matrix, (1920, 1080)), (0, 0), 1.5)


def error_px(shift, truth):
    return max(math.dist(apply(shift["matrix"], p), apply(truth, p)) for p in TEST_POINTS)


def frames(**images):
    return {view: Frame(0.0, image, b"") for view, image in images.items()}


def test_view_shift_recovers_a_known_translation_and_rotation():
    truth, scene = motion(12.5, -7, 0.8), world()
    shift = view_shift(camera(scene), camera(scene, truth))
    assert shift["ok"] and shift["method"] == "ecc"
    assert error_px(shift, truth) < 0.5


def test_view_shift_uses_the_table_marker_when_both_frames_show_it():
    truth, scene = motion(12.5, -7), world(marker=True)
    shift = view_shift(camera(scene), camera(scene, truth))
    assert shift["method"] == "marker" and error_px(shift, truth) < 0.5


def test_view_shift_ignores_the_arm_moving():
    shift = view_shift(camera(world(arm_at=(900, 1000))), camera(world(arm_at=(930, 980))))
    assert shift["moved_px"] < 1 and decide(shift) == "still"


def test_large_shift_asks_for_a_rescan():
    scene = world()
    assert decide(view_shift(camera(scene), camera(scene, motion(150, 0)))) == "rescan"


def test_marker_rebases_base_px_even_when_a_rescan_is_needed(tmp_path, monkeypatch):
    monkeypatch.setitem(BASE_PX, "c922", (1200, 770))
    scene = world(marker=True)
    assert check_views(tmp_path, frames(c922=camera(scene))) == {"action": "no_reference", "views": {}}
    assert not any(tmp_path.iterdir()) and BASE_PX["c922"] == (1200, 770)
    save_reference(tmp_path, frames(c922=camera(scene)))
    check = check_views(tmp_path, frames(c922=camera(scene, motion(120, 90))))
    assert check["action"] == "rescan" and check["views"]["c922"]["method"] == "marker"
    assert BASE_PX["c922"] == pytest.approx((1320, 860), abs=0.5)


def test_rebase_moves_base_px_and_atlas_with_the_view(tmp_path, monkeypatch):
    monkeypatch.setitem(BASE_PX, "c922", (1200, 770))
    monkeypatch.setitem(BASE_PX, "usb", (1130, 880))
    scene = world()
    save_reference(tmp_path, frames(c922=camera(scene), usb=camera(scene)))
    check = check_views(tmp_path, frames(c922=camera(scene), usb=camera(scene, motion(20, -10))))
    assert check["action"] == "rebase"
    assert check["views"]["c922"]["decision"] == "still" and check["views"]["usb"]["decision"] == "rebase"
    assert BASE_PX["c922"] == (1200, 770) and BASE_PX["usb"] == pytest.approx((1150, 870), abs=0.5)
    atlas = [{"pulses": {"base": 1350}, "tip": {"c922": [700.0, 400.0], "usb": [600.0, 500.0]}},
             {"pulses": {"base": 1450}, "tip": {"c922": [720.0, 410.0], "usb": None}}]
    moved = shift_atlas(atlas, "usb", check["views"]["usb"]["matrix"])
    assert moved[0]["tip"]["usb"] == pytest.approx([620, 490], abs=0.5)
    assert moved[0]["tip"]["c922"] == [700.0, 400.0] and moved[1]["tip"]["usb"] is None
    assert atlas[0]["tip"]["usb"] == [600.0, 500.0]


@pytest.mark.parametrize("marker, moved, expected", [(True, motion(120, 90), (1320, 860)),
                                                     (False, motion(20, -10), (1220, 760))])
def test_repeated_checks_shift_base_px_only_once(tmp_path, monkeypatch, marker, moved, expected):
    monkeypatch.setitem(BASE_PX, "c922", (1200, 770))
    scene = world(marker=marker)
    save_reference(tmp_path, frames(c922=camera(scene)))
    for _ in range(2):
        check = check_views(tmp_path, frames(c922=camera(scene, moved)))
        assert check["views"]["c922"]["method"] == ("marker" if marker else "ecc")
    assert BASE_PX["c922"] == pytest.approx(expected, abs=0.5)


def test_decide_fails_closed():
    assert decide({"ok": True, "moved_px": float("nan")}) == "rescan"
    assert decide({"ok": False, "moved_px": 0.0}) == "rescan"


POSES = [{"base": 1350, "shoulder": 1480, "elbow": 2170}, {"base": 1150, "shoulder": 1640, "elbow": 2050},
         {"base": 1550, "shoulder": 1640, "elbow": 2290}]


def linear_atlas():
    return [{"pulses": p, "tip": {"c922": [p["base"] - 400.0, p["shoulder"] - 900.0],
                                  "usb": [p["elbow"] - 1500.0, p["base"] - 800.0]}} for p in serpentine(SCAN_GRID)]


def test_agreement_flags_a_view_whose_tips_left_the_atlas():
    atlas = linear_atlas()

    def seen(c922_drop):
        pairs = []
        for pose in POSES:
            tip = predict_tip(atlas, pose)
            pairs.append((pose, {"c922": [tip["c922"][0], tip["c922"][1] + c922_drop],
                                 "usb": [tip["usb"][0] + 3, tip["usb"][1] + 4]}))
        pairs[1][1]["usb"] = None
        return pairs

    moved = agreement(atlas, seen(25))
    assert not moved["ok"] and moved["error_px"] == pytest.approx({"c922": 25, "usb": 5})
    assert agreement(atlas, seen(15))["ok"]


def test_agreement_needs_a_usb_tip():
    atlas = linear_atlas()
    assert not agreement(atlas, [])["ok"]
    assert not agreement(atlas, [(pose, {"c922": None, "usb": None}) for pose in POSES])["ok"]
    only_c922 = [(pose, {"c922": predict_tip(atlas, pose)["c922"], "usb": None}) for pose in POSES]
    assert not agreement(atlas, only_c922)["ok"]


@pytest.mark.parametrize("action, scan_requested, expected", [
    ("still", False, "continue"), ("rebase", False, "rebase"), ("rescan", True, "scan"), ("rescan", False, "stop"),
    ("no_reference", False, "continue")])
def test_next_action_follows_the_check(action, scan_requested, expected):
    assert next_action({"action": action, "views": {}}, scan_requested) == expected


def test_next_action_rejects_an_unknown_check():
    with pytest.raises(KeyError):
        next_action({"action": "moved", "views": {}}, True)


def test_check_views_uses_saved_corners_when_reference_jpeg_loses_the_tag(tmp_path, monkeypatch):
    monkeypatch.setitem(BASE_PX, "c922", (1200, 770))
    scene = world(marker=True)
    save_reference(tmp_path, frames(c922=camera(scene)))
    # Compression can make a stored tag undecodable while its raw-frame corners remain valid.
    cv2.imwrite(str(tmp_path / "real/calibration/view_reference_c922.jpg"), camera(world()))
    check = check_views(tmp_path, frames(c922=camera(scene, motion(4, -2))))
    shift = check["views"]["c922"]
    assert shift["method"] == "marker" and error_px(shift, motion(4, -2)) < 0.5


@pytest.mark.parametrize("cached", [[[1, 2]], [[float("nan"), 0]] * 4])
def test_view_shift_ignores_invalid_saved_corners(cached):
    image = camera(world(marker=True))
    shift = view_shift(image, image, reference_marker=cached)
    assert shift["method"] == "marker" and shift["moved_px"] < 0.5
