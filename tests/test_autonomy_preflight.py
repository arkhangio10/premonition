import json
from types import SimpleNamespace

import pytest

from inspection import autonomy_run_20261103 as runner


def setup_runner(monkeypatch, tmp_path, check):
    path = tmp_path / "real/calibration/capabilities.json"
    path.parent.mkdir(parents=True)
    atlas = [{"pulses": {"base": 1650}, "tip": {"c922": [700, 400], "usb": [600, 500]}}]
    path.write_bytes(json.dumps({"atlas": atlas, "merged_from": ["one", "two"]}).encode())
    opened, ran, agreed = [], [], []

    class Cameras:
        def __init__(self, host):
            pass
        def start(self):
            pass
        def snapshot(self):
            return {}
        def serve(self):
            return 8767
        def close(self):
            pass

    class Arm:
        def __init__(self, host, root):
            pass
        def __enter__(self):
            opened.append(True)
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr("sys.argv", ["run", "--instruction", "move the sponge"])
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "load_env_file", lambda *args: None)
    monkeypatch.setattr(runner, "client_from_env", lambda: None)
    monkeypatch.setattr(runner, "load_memory", lambda *args: {})
    monkeypatch.setattr(runner, "save_memory", lambda *args: None)
    monkeypatch.setattr(runner, "DualCamera", Cameras)
    monkeypatch.setattr(runner, "ArmSession", Arm)
    monkeypatch.setattr(runner, "check_views", lambda *args: check)
    monkeypatch.setattr(runner, "visit_poses", lambda *args: agreed.append(True) or {"ok": False})
    monkeypatch.setattr(runner, "run_task", lambda *args, **kwargs: ran.append(args[3]) or {"ok": True})
    return atlas, opened, ran, agreed


def check(method="marker", moved=5):
    return {"action": "rebase", "views": {
        "c922": {"decision": "still", "method": "marker", "moved_px": 1, "matrix": [[1, 0, 0], [0, 1, 0]]},
        "usb": {"decision": "rebase", "method": method, "moved_px": moved, "matrix": [[1, 0, 3], [0, 1, 4]]}}}


def test_small_marker_rebase_shifts_atlas_without_visiting_poses(monkeypatch, tmp_path):
    atlas, opened, ran, agreed = setup_runner(monkeypatch, tmp_path, check())
    runner.main()
    assert opened == [True] and not agreed
    assert ran[0][0]["tip"]["usb"] == [603, 504]
    assert atlas[0]["tip"]["usb"] == [600, 500]


@pytest.mark.parametrize("report", [check("ecc", 5), check("marker", 10.1),
    check("marker", float("nan")), {"action": "no_reference", "views": {}}])
def test_untrusted_view_check_stops_before_opening_arm(monkeypatch, tmp_path, report):
    _, opened, ran, agreed = setup_runner(monkeypatch, tmp_path, report)
    with pytest.raises(SystemExit):
        runner.main()
    assert not opened and not ran and not agreed


def test_record_option_keeps_five_seconds_before_and_after_the_task(monkeypatch, tmp_path):
    _, opened, ran, _ = setup_runner(monkeypatch, tmp_path, check())
    sleeps = []
    monkeypatch.setattr("sys.argv", ["run", "--instruction", "move the sponge", "--record"])
    monkeypatch.setattr(runner, "time", SimpleNamespace(sleep=sleeps.append), raising=False)
    runner.main()
    assert opened == [True] and len(ran) == 1 and sleeps == [5, 5]


def test_ecc_still_without_a_tag_stops_before_opening_arm(monkeypatch, tmp_path):
    report = check("marker", 1)
    report["action"] = "still"
    report["views"]["c922"]["method"] = "ecc"
    report["views"]["usb"]["decision"] = "still"
    _, opened, ran, _ = setup_runner(monkeypatch, tmp_path, report)
    with pytest.raises(SystemExit):
        runner.main()
    assert not opened and not ran


def test_runner_restores_the_calibrated_tip_detector_before_the_arm(monkeypatch, tmp_path):
    setup_runner(monkeypatch, tmp_path, check())
    from premonition import visual_servo
    bounds = [[150, 50, 180], [173, 255, 255]]
    path = tmp_path / "real/calibration/capabilities.json"
    data = json.loads(path.read_bytes())
    data["marker_hsv"] = bounds
    path.write_bytes(json.dumps(data).encode())
    monkeypatch.setattr(visual_servo, "MARKER_HSV", None)
    def task(*args, **kwargs):
        assert visual_servo.MARKER_HSV == tuple(tuple(row) for row in bounds)
        return {"ok": True}
    monkeypatch.setattr(runner, "run_task", task)
    runner.main()


def test_repeat_success_option_reaches_the_grasp_policy(monkeypatch, tmp_path):
    setup_runner(monkeypatch, tmp_path, check())
    requested = []
    monkeypatch.setattr("sys.argv", ["run", "--instruction", "move the sponge", "--repeat-success"])
    monkeypatch.setattr(runner, "make_chooser", lambda memory, rng, repeat_success=False:
                        requested.append(repeat_success) or (lambda tries: None))
    runner.main()
    assert requested == [True]
