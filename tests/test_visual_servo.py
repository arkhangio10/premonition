import cv2
import numpy as np
import pytest

from premonition import visual_servo
from premonition.visual_servo import (BACKLASH_US, BASE_PX, MAX_RETRIES, MAX_STEP_US, LoopState, decide,
                                       locate_tip)

PULSES = {"base": 1600, "shoulder": 1440, "elbow": 1675}


def state(target=(600, 500), **fields):
    return LoopState(target=target, **fields)


BLUE, WHITE = (230, 120, 30), (250, 250, 250)


def arm(*joints, base=BASE_PX["c922"], housing=60):
    """Blue links from the base through each joint, with a white housing at the start of every later link."""
    image = np.full((1080, 1920, 3), (150, 140, 135), np.uint8)
    cv2.line(image, base, joints[0], BLUE, 40)
    for start, end in zip(joints, joints[1:]):
        direction = np.subtract(end, start) / np.hypot(*np.subtract(end, start))
        housing_end = tuple(int(v) for v in np.add(start, housing * direction))
        cv2.line(image, start, housing_end, WHITE, 40)
        cv2.line(image, housing_end, end, BLUE, 40)
    return image


def test_tip_is_the_far_end_of_the_blue_arm_across_the_white_housing():
    assert locate_tip(arm((900, 350), (600, 470))) == pytest.approx((600, 470), abs=25)


def test_tip_follows_a_gripper_that_points_back_toward_the_table():
    assert locate_tip(arm((850, 300), (760, 640))) == pytest.approx((760, 640), abs=25)


def test_second_camera_measures_from_its_own_base():
    image = arm((760, 300), (380, 200), base=BASE_PX["usb"])
    assert locate_tip(image, BASE_PX["usb"]) == pytest.approx((380, 200), abs=25)


def test_housing_seen_wide_from_the_side_is_still_bridged():
    assert locate_tip(arm((900, 350), (500, 420), housing=150)) == pytest.approx((500, 420), abs=25)


def test_tip_does_not_jump_between_two_nearly_equal_jaws():
    def gripper(upper, lower):
        image = arm((900, 350), (700, 420))
        cv2.line(image, (700, 420), (700 - upper, 380), BLUE, 24)
        cv2.line(image, (700, 420), (700 - lower, 470), BLUE, 24)
        return image
    first, second = locate_tip(gripper(130, 124)), locate_tip(gripper(124, 130))
    assert np.hypot(first[0] - second[0], first[1] - second[1]) < 15


def test_blue_object_away_from_the_arm_is_ignored():
    image = arm((900, 350), (600, 470))
    cv2.rectangle(image, (1400, 300), (1700, 400), BLUE, -1)
    assert locate_tip(image) == pytest.approx((600, 470), abs=25)


def test_without_a_blue_arm_at_the_base_the_tip_is_lost():
    image = np.full((1080, 1920, 3), (215, 215, 215), np.uint8)
    cv2.rectangle(image, (590, 500), (750, 700), (40, 130, 250), -1)
    cv2.rectangle(image, (1400, 300), (1700, 400), BLUE, -1)
    assert locate_tip(image) is None


def test_short_blue_patch_at_the_base_is_not_taken_for_the_arm():
    image = np.full((1080, 1920, 3), (150, 140, 135), np.uint8)
    x, y = BASE_PX["usb"]
    cv2.rectangle(image, (x - 40, y - 40), (x, y), BLUE, -1)
    assert locate_tip(image, BASE_PX["usb"]) is None


def test_lost_tip_stops_without_moving():
    decision = decide(state(), None, PULSES)
    assert (decision.kind, decision.reason) == ("stop", "tip_not_visible")


def test_tip_within_tolerance_is_done():
    assert decide(state(), (603, 505), PULSES).kind == "done"


def test_vertical_error_is_assigned_to_the_shoulder():
    decision = decide(state(), (600, 440), PULSES)
    assert (decision.kind, decision.joint) == ("move", "shoulder") and decision.delta < 0


def test_horizontal_error_is_assigned_to_the_base():
    decision = decide(state(), (500, 460), PULSES)
    assert (decision.kind, decision.joint) == ("move", "base") and decision.delta > 0


def test_step_never_exceeds_the_reviewed_cap():
    assert abs(decide(state(), (100, 500), PULSES).delta) <= MAX_STEP_US


def test_changing_direction_adds_the_measured_backlash():
    same = decide(state(direction={"shoulder": -1}), (600, 440), PULSES).delta
    reversed_step = decide(state(direction={"shoulder": 1}), (600, 440), PULSES).delta
    assert reversed_step == same - BACKLASH_US


def test_steps_stay_inside_the_traversed_box():
    decision = decide(state(), (600, 300), {"base": 1685, "shoulder": 1367, "elbow": 1733})
    assert (decision.kind, decision.reason) == ("stop", "out_of_reach")


def test_small_remaining_error_is_still_corrected():
    decision = decide(state(target=(590, 500)), (597, 517), {"base": 1743, "shoulder": 1367, "elbow": 1616})
    assert (decision.kind, decision.joint) == ("move", "elbow")


def test_error_below_the_smallest_useful_step_reports_the_resolution_limit():
    decision = decide(state(target=(590, 500)), (601, 489), {"base": 1743, "shoulder": 1367, "elbow": 1587})
    assert (decision.kind, decision.reason) == ("stop", "resolution_limit")


def test_step_without_visible_motion_retries_wider_on_the_same_joint():
    loop = state()
    first = decide(loop, (600, 440), PULSES)
    second = decide(loop, (600, 441), dict(PULSES, shoulder=PULSES["shoulder"] + first.delta))
    assert second.joint == first.joint and abs(second.delta) > abs(first.delta)
    assert loop.retries == 1


def test_persistent_lack_of_motion_stops_instead_of_pushing():
    loop, pulses = state(), dict(PULSES)
    decision = decide(loop, (500, 460), pulses)
    for _ in range(MAX_RETRIES):
        pulses["base"] += decision.delta
        decision = decide(loop, (500, 460), pulses)
        assert decision.kind == "move"
    pulses["base"] += decision.delta
    decision = decide(loop, (500, 460), pulses)
    assert (decision.kind, decision.reason) == ("stop", "stalled:base")


def test_visible_motion_clears_retries_and_corrects_the_sensitivity():
    loop = state(retries=1)
    first = decide(loop, (600, 440), PULSES)
    before = loop.sensitivity["shoulder"][1]
    decide(loop, (600, 480), dict(PULSES, shoulder=PULSES["shoulder"] + first.delta))
    assert loop.retries == 0
    assert abs(loop.sensitivity["shoulder"][1]) < abs(before)


def test_move_limit_stops_the_loop():
    decision = decide(state(moves=12), (600, 440), PULSES)
    assert (decision.kind, decision.reason) == ("stop", "move_limit")


def test_moving_away_from_the_target_stops_the_loop():
    loop = state()
    first = decide(loop, (600, 440), PULSES)
    decision = decide(loop, (600, 300), dict(PULSES, shoulder=PULSES["shoulder"] + first.delta))
    assert (decision.kind, decision.reason) == ("stop", "diverging")


def ring_on_jaw(tip, color=(200, 0, 200)):
    image = arm(BASE_PX["usb"], (900, 500))
    cv2.ellipse(image, tip, (22, 14), 30, 0, 360, color, -1)
    return image


def test_marker_tip_is_the_centroid_of_the_magenta_ring(monkeypatch):
    monkeypatch.setattr(visual_servo, "MARKER_HSV", ((140, 80, 80), (172, 255, 255)))
    x, y = visual_servo.locate_marker_tip(ring_on_jaw((900, 500)))
    assert abs(x - 900) < 1 and abs(y - 500) < 1


def test_marker_ignores_red_led_and_orange_sponge(monkeypatch):
    monkeypatch.setattr(visual_servo, "MARKER_HSV", ((140, 80, 80), (172, 255, 255)))
    image = arm(BASE_PX["usb"], (900, 500))
    cv2.circle(image, (700, 300), 12, (0, 0, 255), -1)
    cv2.circle(image, (700, 300), 24, (60, 60, 200), 6)
    cv2.rectangle(image, (1200, 600), (1400, 700), (40, 130, 250), -1)
    assert visual_servo.locate_marker_tip(image) is None


def test_marker_detector_is_off_until_configured(monkeypatch):
    monkeypatch.setattr(visual_servo, "MARKER_HSV", None)
    assert visual_servo.MARKER_HSV is None
    assert visual_servo.locate_marker_tip(ring_on_jaw((900, 500))) is None


def test_proposed_marker_range_covers_the_tape_and_excludes_red_and_orange(monkeypatch):
    image = ring_on_jaw((900, 500))
    cv2.circle(image, (700, 300), 12, (0, 0, 255), -1)
    cv2.rectangle(image, (1200, 600), (1400, 700), (40, 130, 250), -1)
    stats = visual_servo.hsv_percentiles(image, (890, 495, 910, 505))
    low, high = visual_servo.propose_marker_hsv([stats])
    assert all(l <= v <= h for l, v, h in zip(low, cv2.cvtColor(np.uint8([[(200, 0, 200)]]), cv2.COLOR_BGR2HSV)[0, 0], high))
    for color in ((0, 0, 255), (40, 130, 250)):
        pixel = cv2.cvtColor(np.uint8([[color]]), cv2.COLOR_BGR2HSV)[0, 0]
        assert not all(l <= v <= h for l, v, h in zip(low, pixel, high))
    monkeypatch.setattr(visual_servo, "MARKER_HSV", (low, high))
    x, y = visual_servo.locate_marker_tip(image)
    assert abs(x - 900) < 2 and abs(y - 500) < 2


def test_contaminated_box_still_proposes_a_tight_range(monkeypatch):
    image = ring_on_jaw((900, 500))
    cv2.circle(image, (700, 300), 12, (0, 0, 255), -1)
    cv2.rectangle(image, (1200, 600), (1400, 700), (40, 130, 250), -1)
    low, high = visual_servo.propose_marker_hsv([visual_servo.hsv_percentiles(image, (884, 492, 916, 508))])
    assert visual_servo.hsv_percentiles(image, (0, 0, 10, 10)) is None
    pixel = cv2.cvtColor(np.uint8([[(200, 0, 200)]]), cv2.COLOR_BGR2HSV)[0, 0]
    assert all(l <= v <= h for l, v, h in zip(low, pixel, high))
    for color in ((0, 0, 255), (40, 130, 250), tuple(image[10, 10])):
        pixel = cv2.cvtColor(np.uint8([[color]]), cv2.COLOR_BGR2HSV)[0, 0]
        assert not all(l <= v <= h for l, v, h in zip(low, pixel, high))
    accepted = cv2.inRange(cv2.cvtColor(image, cv2.COLOR_BGR2HSV), low, high).mean() / 255
    assert accepted < 0.01
