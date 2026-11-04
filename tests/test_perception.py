import cv2
import numpy as np
import pytest

from premonition.models import CaptureRequest, Contract, Frame, Predicate
from premonition.perception import check_frame, decode_image, frame_issues, measure_scene
from premonition.sim import SCENARIOS, SimWorld, simulated_reference
from premonition.verifier import judge_a2, judge_a3


def contract(action="place", role="post", piece="A", predicates=()):
    return Contract(
        contract_id="c1", run_id="r1", step_id="s4", attempt=1, plan_sha256="p", action=action,
        role=role, piece_id=piece, predicates=list(predicates), initial_frame_sha256=None,
        reference_sha256=None, reference_source=None, thresholds_sha256="t")


def scene(sim_cell, setup=None, occlude_region=None):
    world = SimWorld(SCENARIOS["success"], sim_cell)
    if setup:
        setup(world)
    return world.render(seq=1, occlude_region=occlude_region)


def judge(sim_cell, jpeg, case):
    return judge_a2(case, measure_scene(decode_image(jpeg), sim_cell), sim_cell.perception)


PRESENT_A = Predicate(kind="piece_present", region="left", piece="A")
EMPTY_SOURCE = Predicate(kind="region_empty", region="src_a")


def test_empty_source_passes_after_the_piece_left(sim_cell):
    jpeg = scene(sim_cell, lambda w: w.put("A", "left"))
    assert judge(sim_cell, jpeg, contract("pick", piece="A", predicates=[EMPTY_SOURCE])).outcome == "pass"


def test_piece_at_destination_passes(sim_cell):
    jpeg = scene(sim_cell, lambda w: w.put("A", "left"))
    assert judge(sim_cell, jpeg, contract(predicates=[PRESENT_A])).outcome == "pass"


def test_piece_still_at_source_is_a_failed_grasp(sim_cell):
    verdict = judge(sim_cell, scene(sim_cell), contract("pick", piece="A", predicates=[EMPTY_SOURCE]))
    assert (verdict.outcome, verdict.failure_class) == ("fail", "grasp_failed")


def test_absent_piece_at_destination_is_a_lost_piece(sim_cell):
    verdict = judge(sim_cell, scene(sim_cell), contract(predicates=[PRESENT_A]))
    assert (verdict.outcome, verdict.failure_class) == ("fail", "piece_lost")


def test_other_piece_at_destination_is_wrong_piece(sim_cell):
    jpeg = scene(sim_cell, lambda w: w.put("B", "left"))
    verdict = judge(sim_cell, jpeg, contract(predicates=[PRESENT_A]))
    assert (verdict.outcome, verdict.failure_class) == ("fail", "wrong_piece")


def test_piece_outside_tolerance_is_misplaced(sim_cell):
    jpeg = scene(sim_cell, lambda w: w.put("A", "left", offset=(50, 0)))
    verdict = judge(sim_cell, jpeg, contract(predicates=[PRESENT_A]))
    assert (verdict.outcome, verdict.failure_class) == ("fail", "misplaced")


def test_required_piece_missing_at_inspection(sim_cell):
    jpeg = scene(sim_cell, lambda w: w.remove("A"))
    predicate = Predicate(kind="piece_present", region="src_a", piece="A")
    verdict = judge(sim_cell, jpeg, contract("inspect_scene", "inspect", None, [predicate]))
    assert (verdict.outcome, verdict.failure_class) == ("fail", "missing_piece")


def test_occluded_region_is_unknown_never_pass(sim_cell):
    jpeg = scene(sim_cell, lambda w: w.put("A", "left"), occlude_region="left")
    verdict = judge(sim_cell, jpeg, contract(predicates=[PRESENT_A]))
    assert verdict.outcome == "unknown"
    assert any("region_occluded" in reason for reason in verdict.reasons)


def test_occluded_empty_check_is_unknown_never_pass(sim_cell):
    image = decode_image(scene(sim_cell, lambda w: w.remove("A"), occlude_region="src_a"))
    verdict = judge_a2(contract("pick", piece="A", predicates=[EMPTY_SOURCE]),
                       measure_scene(image, sim_cell), sim_cell.perception)
    assert verdict.outcome == "unknown"


def test_small_fragment_is_ambiguous_occupancy(sim_cell):
    image = decode_image(scene(sim_cell, lambda w: w.remove("A")))
    region = sim_cell.location("src_a").region
    image[region.y + 60:region.y + 100, region.x + 60:region.x + 100] = (40, 40, 210)
    verdict = judge_a2(contract("pick", piece="A", predicates=[EMPTY_SOURCE]),
                       measure_scene(image, sim_cell), sim_cell.perception)
    assert verdict.outcome == "unknown"
    assert any("occupancy_ambiguous" in reason for reason in verdict.reasons)


def test_mixed_colors_are_ambiguous_identity(sim_cell):
    image = decode_image(scene(sim_cell, lambda w: w.remove("A")))
    region = sim_cell.location("src_a").region
    image[region.y + 40:region.y + 120, region.x + 40:region.x + 80] = (40, 40, 210)
    image[region.y + 40:region.y + 120, region.x + 80:region.x + 120] = (60, 180, 60)
    predicate = Predicate(kind="piece_present", region="src_a", piece="A")
    verdict = judge_a2(contract("inspect_scene", "inspect", None, [predicate]),
                       measure_scene(image, sim_cell), sim_cell.perception)
    assert verdict.outcome == "unknown"
    assert any("identity_ambiguous" in reason for reason in verdict.reasons)


def request(**overrides):
    fields = dict(run_id="r1", step_id="s4", attempt=1, phase="post", command_id="m1", token="t1")
    return CaptureRequest(**(fields | overrides))


def frame(jpeg=b"x", sha=None, **overrides):
    import hashlib
    sha = hashlib.sha256(jpeg).hexdigest() if sha is None else sha
    fields = dict(frame_id="f1", run_id="r1", step_id="s4", attempt=1, phase="post",
                  command_id="m1", token="t1", source="synthetic", jpeg=jpeg, sha256=sha)
    return Frame(**(fields | overrides))


@pytest.mark.parametrize("field, value, code", [
    ("run_id", "r2", "wrong_run"),
    ("step_id", "s9", "wrong_step"),
    ("attempt", 2, "wrong_attempt"),
    ("phase", "pre", "wrong_phase"),
    ("command_id", "m0", "wrong_command"),
    ("token", "t0", "stale_token"),
])
def test_frame_from_another_context_is_rejected(field, value, code):
    assert code in check_frame(frame(**{field: value}), request(), seen=set())


def test_empty_frame_is_rejected():
    assert "empty_frame" in check_frame(frame(jpeg=b""), request(), seen=set())


def test_repeated_image_is_rejected_as_stale():
    assert "repeated_image" in check_frame(frame(sha="h1"), request(), seen={"h1"})


def test_matching_frame_has_no_context_issues():
    assert check_frame(frame(), request(), seen=set()) == []


def test_undecodable_frame_is_a_quality_issue(sim_cell):
    assert frame_issues(b"not a jpeg", sim_cell.perception) == ["undecodable_image"]


def test_clean_synthetic_frame_has_no_quality_issues(sim_cell):
    assert frame_issues(scene(sim_cell), sim_cell.perception) == []


def _encode(image):
    return cv2.imencode(".jpg", image)[1].tobytes()


def test_overexposed_frame_is_rejected(sim_cell):
    white = np.full((540, 960, 3), 255, np.uint8)
    issues = frame_issues(_encode(white), sim_cell.perception)
    assert "overexposed" in issues and "too_bright" in issues


def test_dark_frame_is_rejected(sim_cell):
    assert "too_dark" in frame_issues(_encode(np.zeros((540, 960, 3), np.uint8)), sim_cell.perception)


def test_blurred_frame_is_rejected(sim_cell):
    blurred = cv2.GaussianBlur(decode_image(scene(sim_cell)), (41, 41), 15)
    assert "blurred" in frame_issues(_encode(blurred), sim_cell.perception)


def test_a3_matches_a2_when_the_reference_agrees(sim_cell):
    case = contract(predicates=[PRESENT_A])
    jpeg = scene(sim_cell, lambda w: w.put("A", "left"))
    a2 = judge(sim_cell, jpeg, case)
    reference = simulated_reference(scene(sim_cell), case, sim_cell)
    a3, similarity = judge_a3(a2, case, jpeg, reference, sim_cell)
    assert a3.outcome == "pass" and similarity["left"] > sim_cell.perception.reference_similarity_min


def test_a3_abstains_when_the_observation_contradicts_the_reference(sim_cell):
    case = contract(predicates=[PRESENT_A])
    jpeg = scene(sim_cell, lambda w: w.put("A", "left"))
    a2 = judge(sim_cell, jpeg, case)
    contradictory = scene(sim_cell, lambda w: w.put("B", "left"))
    a3, _ = judge_a3(a2, case, jpeg, contradictory, sim_cell)
    assert a3.outcome == "unknown" and "reference_mismatch" in a3.reasons[0]


def test_a3_can_never_turn_a_failure_into_a_pass(sim_cell):
    case = contract(predicates=[PRESENT_A])
    observed = scene(sim_cell, lambda w: w.put("B", "left"))
    a2 = judge(sim_cell, observed, case)
    a3, _ = judge_a3(a2, case, observed, observed, sim_cell)
    assert a2.outcome == "fail" and a3 == a2


def test_a3_without_reference_keeps_a2_and_says_so(sim_cell):
    case = contract(predicates=[PRESENT_A])
    jpeg = scene(sim_cell, lambda w: w.put("A", "left"))
    a2 = judge(sim_cell, jpeg, case)
    a3, similarity = judge_a3(a2, case, jpeg, None, sim_cell)
    assert a3.outcome == a2.outcome and similarity == {} and "reference_missing" in a3.reasons


@pytest.mark.parametrize("region, piece", [("src_a", "A"), ("src_b", "B"), ("src_c", "C")])
def test_a3_treats_two_empty_regions_as_a_match(sim_cell, region, piece):
    case = contract("pick", piece=piece, predicates=[Predicate(kind="region_empty", region=region)])
    after = scene(sim_cell, lambda w: w.remove(piece))
    a2 = judge(sim_cell, after, case)
    a3, similarity = judge_a3(a2, case, after, simulated_reference(scene(sim_cell), case, sim_cell), sim_cell)
    assert a3.outcome == "pass" and similarity[region] == 1.0


def test_a3_abstains_when_the_reference_expects_empty_and_the_region_is_occupied(sim_cell):
    region_empty = Predicate(kind="region_empty", region="src_a")
    case = contract("pick", piece="A", predicates=[region_empty])
    observed = scene(sim_cell, lambda w: w.remove("A"))
    a2 = judge(sim_cell, observed, case)
    occupied_reference = scene(sim_cell)
    a3, similarity = judge_a3(a2, case, observed, occupied_reference, sim_cell)
    assert a3.outcome == "unknown" and similarity["src_a"] == 0.0
