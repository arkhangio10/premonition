from copy import deepcopy

import pytest

from inspection.approach_probe_20261102 import EXPECTED, build_command, build_repeat_command, build_base_command, validate_readback, build_review_command, validate_capture_review


def reading():
    return {"mode1": 33, "prescale": 121, "commanded_us": dict(EXPECTED)}


def test_direction_probe_only_changes_shoulder_slowly():
    before = reading()
    saved = deepcopy(before)
    command = build_command(before)
    assert before == saved
    assert command["cmd"] == "move" and command["duration"] == 3
    assert command["targets"]["shoulder"] == 1430
    assert [j for j in EXPECTED if before["commanded_us"][j] != command["targets"][j]] == ["shoulder"]
    assert 20 / command["duration"] < 7


@pytest.mark.parametrize("key,value", [("mode1",17),("prescale",30)])
def test_sleep_or_changed_frequency_prevents_probe(key,value):
    before = reading()
    before[key] = value
    with pytest.raises(ValueError):
        build_command(before)


@pytest.mark.parametrize("joint", list(EXPECTED))
@pytest.mark.parametrize("value", [None, 1600, True])
def test_any_changed_or_released_channel_prevents_probe(joint,value):
    before = reading()
    before["commanded_us"][joint] = value
    with pytest.raises(ValueError):
        build_command(before)


@pytest.mark.parametrize("phase,start,target",[("repeat_return",1431,1450),("repeat_probe",1450,1430),("wider_probe",1431,1370)])
def test_requested_repeat_has_exact_start_and_changes_only_shoulder(phase,start,target):
    before=reading()
    before["commanded_us"]["shoulder"]=start
    command=build_repeat_command(before,phase)
    assert command["targets"]["shoulder"]==target
    assert command["duration"]==(4 if phase=="wider_probe" else 3)
    assert abs(target-start)/command["duration"] <= 16
    assert all(command["targets"][j]==before["commanded_us"][j] for j in EXPECTED if j!="shoulder")
    before["commanded_us"]["base"]+=5
    with pytest.raises(ValueError):
        build_repeat_command(before,phase)


@pytest.mark.parametrize("phase,start",[("repeat_return",1450),("repeat_probe",1431),("other",1450)])
def test_unexpected_repeat_state_or_phase_cannot_be_sent(phase,start):
    before=reading()
    before["commanded_us"]["shoulder"]=start
    with pytest.raises(ValueError):
        build_repeat_command(before,phase)


def test_base_probe_only_rotates_base_from_confirmed_checkpoint():
    before=reading()
    before["commanded_us"]["shoulder"]=1372
    command=build_base_command(before)
    assert command["targets"]==dict(before["commanded_us"],base=1559)
    assert command["duration"]==4
    after=deepcopy(before)
    after["commanded_us"]["base"]=1557
    validate_readback(before,after,command)
    before["commanded_us"]["gripper"]=1499
    with pytest.raises(ValueError):
        build_base_command(before)


@pytest.mark.parametrize("joint",list(EXPECTED))
def test_readback_rejects_drift_in_every_uncommanded_joint_or_bad_target(joint):
    before=reading()
    command=build_command(before)
    after=deepcopy(before)
    after["commanded_us"]["shoulder"]=1431
    after["commanded_us"][joint]+=10
    with pytest.raises(ValueError):
        validate_readback(before,after,command)


def step_review(joint="elbow",delta=60):
    before=reading()
    before["commanded_us"].update(base=1558,shoulder=1372)
    review={"expected_readback":deepcopy(before),"table_prepared_operator_confirmed":True,
            "command":{"id":1,"cmd":"move","targets":dict(before["commanded_us"],**{joint:before["commanded_us"][joint]+delta}),"duration":4.0}}
    return before,review


@pytest.mark.parametrize("joint",list(EXPECTED))
def test_reviewed_step_has_exactly_one_joint_slow_cap_and_unchanged_input(joint):
    before,review=step_review(joint)
    saved=deepcopy(review)
    command=build_review_command(before,review)
    assert command==review["command"] and review==saved
    assert abs(command["targets"][joint]-before["commanded_us"][joint])/command["duration"]==15


@pytest.mark.parametrize("case",["drift","two_joints","too_far","released","float","endpoint","fast","no_confirmation"])
def test_review_cannot_expand_into_an_unreviewed_move(case):
    before,review=step_review()
    if case=="drift": before["commanded_us"]["shoulder"]-=1
    if case=="two_joints": review["command"]["targets"]["base"]+=1
    if case=="too_far": review["command"]["targets"]["elbow"]+=1
    if case=="released": before["commanded_us"]["elbow"]=None
    if case=="float": review["command"]["targets"]["elbow"]=1559.0
    if case=="endpoint": review["command"]["targets"]["elbow"]=2300
    if case=="fast": review["command"]["duration"]=.1
    if case=="no_confirmation": review["table_prepared_operator_confirmed"]=False
    with pytest.raises(ValueError):
        build_review_command(before,review)


def test_elbow_may_fold_past_2000_us_to_reach_the_table():
    before,review=step_review()
    before["commanded_us"]["elbow"]=1997
    review=step_review()[1]|{"expected_readback":deepcopy(before)}
    review["command"]["targets"]=dict(before["commanded_us"],elbow=2057)
    assert build_review_command(before,review)["targets"]["elbow"]==2057


def test_physical_step_must_use_the_exact_visually_reviewed_image():
    capture={"file":"new.jpg","sha256":"a"*64}
    review={"reviewed_capture_file":"new.jpg","reviewed_capture_sha256":"a"*64}
    validate_capture_review(review,capture)
    for change in ({"file":"later.jpg"},{"sha256":"b"*64}):
        with pytest.raises(ValueError):validate_capture_review(review,capture|change)
    with pytest.raises(ValueError):validate_capture_review({},capture)
