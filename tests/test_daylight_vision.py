from pathlib import Path

import cv2
import numpy as np
import pytest

from premonition.view_check import table_marker
from premonition.scene_detect import locate_object


@pytest.mark.parametrize("view", ["c922", "usb"])
def test_table_marker_decodes_the_recorded_daylight_tag(view):
    image = cv2.imread(str(Path(__file__).parent / "fixtures" / f"daylight_tag_{view}.png"))
    assert image is not None
    corners = table_marker(image)
    assert corners is not None and corners.shape == (4, 2)
    assert np.all(corners >= 0)
    assert np.all(corners < np.array(image.shape[1::-1]))


def test_table_marker_still_rejects_a_different_tag_id():
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    tag = cv2.aruco.generateImageMarker(dictionary, 1, 180)
    gray = np.full((260, 260), 255, np.uint8)
    gray[40:220, 40:220] = tag
    assert table_marker(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)) is None


def test_daylight_front_sponge_in_shadow_keeps_its_full_width():
    image = cv2.imread(str(Path(__file__).parent / "fixtures" / "daylight_sponge_c922.png"))
    found = locate_object(image)
    assert found is not None
    assert found["x1"] - found["x0"] >= 240
    assert found["top"] < 60
