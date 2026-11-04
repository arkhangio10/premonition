import sys

import pytest

from premonition.teaching_hold import MotionHeld,require_no_motion_hold


@pytest.mark.parametrize("content",['{"reason":"vibration"}',"",'{"active":false}',"broken json"])
def test_any_persisted_hold_blocks_motion_even_if_partial_or_malformed(tmp_path,content):
    path=tmp_path/"real/calibration/motion_hold.json"
    path.parent.mkdir(parents=True)
    path.write_text(content,encoding="utf-8")
    with pytest.raises(MotionHeld):require_no_motion_hold(tmp_path)


def test_no_hold_does_not_create_files_or_access_hardware(tmp_path):
    require_no_motion_hold(tmp_path)
    assert not list(tmp_path.iterdir())


def test_held_probe_cannot_even_inspect_or_start_a_controller(tmp_path,monkeypatch):
    from inspection import approach_probe_20261102 as probe
    path=tmp_path/"real/calibration/motion_hold.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}",encoding="utf-8")
    monkeypatch.setattr(probe,"ROOT",tmp_path)
    monkeypatch.setattr(sys,"argv",["probe","--review","teaching_step_any.json"])
    def forbidden(*args,**kwargs):pytest.fail("Held probe must not reach hardware or spawn a controller")
    monkeypatch.setattr(probe,"inspect_system",forbidden)
    monkeypatch.setattr(probe.subprocess,"Popen",forbidden)
    with pytest.raises(MotionHeld):probe.main()


@pytest.mark.parametrize("command",["decide","execute"])
def test_visual_approach_cannot_reach_camera_or_controller_while_held(tmp_path,monkeypatch,command):
    from inspection import visual_approach_20261102 as runner
    path=tmp_path/"real/calibration/motion_hold.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}",encoding="utf-8")
    monkeypatch.setattr(runner,"ROOT",tmp_path)
    monkeypatch.setattr(sys,"argv",["approach",command,"--run","hover01"])
    def forbidden(*args,**kwargs):pytest.fail("Held loop must not access hardware")
    monkeypatch.setattr(runner,"read_commanded_pulses",forbidden)
    monkeypatch.setattr(runner.httpx,"Client",forbidden)
    with pytest.raises(MotionHeld):runner.main()


@pytest.mark.parametrize("module_name,argv",[
    ("inspection.restart_home_20261102",["home"]),
    ("inspection.wrist_view_probe_20261102",["wrist","--joint","gripper","--target","1618"]),
])
def test_historical_motion_helpers_also_obey_hold(tmp_path,monkeypatch,module_name,argv):
    import importlib
    probe=importlib.import_module(module_name)
    path=tmp_path/"real/calibration/motion_hold.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}",encoding="utf-8")
    monkeypatch.setattr(probe,"ROOT",tmp_path)
    monkeypatch.setattr(sys,"argv",argv)
    def forbidden(*args,**kwargs):pytest.fail("Held helper must not access hardware")
    monkeypatch.setattr(probe,"inspect_system",forbidden)
    with pytest.raises(MotionHeld):probe.main()
