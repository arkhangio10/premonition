import copy

import pytest

from inspection.wrist_view_probe_20261102 import HOME, build_command


def reading(**pulses):
    return {"mode1":33,"prescale":121,"commanded_us":HOME|pulses}


@pytest.mark.parametrize("joint,start,target", [("wrist_roll",1499,1579),("wrist_roll",1577,1657),
                                              ("wrist_roll",1655,1499),("gripper",1499,1618)])
def test_one_known_joint_changes_slowly_without_starting_other_channels(joint,start,target):
    before = reading(**{joint:start})
    saved = copy.deepcopy(before)
    command = build_command(before,joint,target)
    assert before == saved
    assert command["cmd"] == "move" and command["duration"] == 3
    assert [j for j in HOME if command["targets"][j] != before["commanded_us"][j]] == [joint]
    assert abs(target-start)/command["duration"] <= 52


@pytest.mark.parametrize("joint,target,pulses", [("base",1520,{}),("wrist_roll",1750,{}),
    ("wrist_roll",1579,{"shoulder":1460}),("wrist_roll",1579,{"gripper":1616}),
    ("gripper",1950,{}),("wrist_roll",1579,{"elbow":None})])
def test_unobserved_ranges_or_changed_support_are_rejected(joint,target,pulses):
    with pytest.raises(ValueError):
        build_command(reading(**pulses),joint,target)


def test_controller_sleep_or_wrong_frequency_is_rejected():
    for key,value in [("mode1",17),("prescale",30)]:
        with pytest.raises(ValueError):
            build_command(reading()|{key:value},"wrist_roll",1579)
