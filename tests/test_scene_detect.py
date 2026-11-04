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
    assert abs(found["top"] - 700) <= 5 and abs(found["bottom"] - 800) <= 5
