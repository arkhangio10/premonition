import cv2
import numpy as np

from premonition.scene_detect import locate_object


def scene(background=(200, 200, 200)):
    return np.full((1080, 1920, 3), background, np.uint8)


def test_orange_sponge_is_found_with_its_top_edge():
    image = scene()
    cv2.rectangle(image, (600, 500), (800, 700), (40, 130, 250), -1)
    found = locate_object(image)
    assert abs(found["top"] - 500) <= 5 and abs(found["x0"] - 600) <= 5
    assert abs(found["bottom"] - 700) <= 5 and abs(found["x1"] - 800) <= 5
    assert abs(found["cx"] - 700) <= 5 and abs(found["cy"] - 600) <= 5 and found["area"] > 39000


def test_brown_table_is_not_taken_for_the_sponge():
    hsv = np.full((1080, 1920, 3), (13, 124, 150), np.uint8)
    assert locate_object(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)) is None


def test_small_orange_specks_are_ignored():
    image = scene()
    cv2.rectangle(image, (600, 500), (639, 549), (40, 130, 250), -1)
    assert locate_object(image) is None


def test_washed_out_sponge_is_found_and_shadowed_red_board_is_not():
    hsv = np.full((1080, 1920, 3), (100, 30, 200), np.uint8)
    hsv[680:830, 600:800] = (14, 135, 252)
    hsv[860:960, 650:900] = (7, 172, 110)
    found = locate_object(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR))
    assert abs(found["x0"] - 600) <= 5 and abs(found["top"] - 680) <= 5 and abs(found["bottom"] - 830) <= 5


def test_reddish_shaded_face_of_the_sponge_is_found():
    hsv = np.full((1080, 1920, 3), (100, 30, 200), np.uint8)
    hsv[650:700, 600:800] = (9, 120, 240)
    hsv[700:800, 600:800] = (6, 175, 200)
    found = locate_object(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR))
    assert abs(found["top"] - 650) <= 5 and abs(found["bottom"] - 800) <= 5


def test_daylight_usb_sponge_with_hue_one_to_three_is_found():
    for hue in (1, 2, 3):
        hsv = np.full((1080, 1920, 3), (13, 124, 150), np.uint8)
        hsv[650:790, 620:830] = (hue, 145, 215)
        found = locate_object(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR))
        assert found is not None
        assert abs(found["top"] - 650) <= 5 and abs(found["x0"] - 620) <= 5


def test_connected_pale_usb_face_keeps_the_real_left_and_top_edges():
    from pathlib import Path
    image = cv2.imread(str(Path(__file__).parent / "fixtures/daylight_sponge_usb_pale.png"))
    found = locate_object(image)
    assert found is not None and 40 <= found["x0"] <= 80 and 15 <= found["top"] <= 45
    assert found["x1"] - found["x0"] >= 210


def test_washed_out_usb_face_with_a_small_saturated_core_is_found():
    # 4 Nov 16:05: after the USB remount the face read S ~104 and its S >= 130 core fell to 1200-4700 px,
    # so 38 % of still frames lost the sponge and the grasp stopped with object_not_found.
    hsv = np.full((1080, 1920, 3), (13, 124, 150), np.uint8)
    hsv[620:770, 590:820] = (4, 104, 210)
    hsv[680:720, 650:690] = (4, 150, 210)
    found = locate_object(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR))
    assert found is not None and abs(found["x0"] - 590) <= 5 and abs(found["top"] - 620) <= 5


def test_a_bright_weak_orange_region_without_a_saturated_seed_is_rejected():
    hsv = np.full((1080, 1920, 3), (13, 124, 230), np.uint8)
    assert locate_object(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)) is None
