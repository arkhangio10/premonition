import cv2
import numpy as np

from premonition.arm_model import (NOMINAL, ArmModel, chain, fit, fk, from_json, holdout, levenberg_marquardt, model_for,
                                   project, scale_from_marker, tip_error_mm, to_json, triangulate, workspace)
from inspection.arm_checks_20261103 import holdout_errors
from premonition.atlas import SCAN_GRID

KIN = {"g_base": 0.001, "g_shoulder": 0.001, "g_elbow": -0.001, "z_shoulder": 1500, "a1": 0.05, "u": 1.8, "v": 0.2, "d": 0.1}
TRUE_KIN = {"g_base": 1.1 * np.pi / 2000, "g_shoulder": 1.18 * np.pi / 2000, "g_elbow": -1.18 * np.pi / 2000,
            "z_shoulder": 1600, "a1": 0.06, "u": 1.95, "v": 0.1, "d": 0.05}
POSES = [{"base": b, "shoulder": s, "elbow": e} for b in SCAN_GRID["base"] for s in SCAN_GRID["shoulder"] for e in SCAN_GRID["elbow"]]


def synthetic_model():
    rvec = lambda ry: cv2.Rodrigues(cv2.Rodrigues(np.array([np.pi, 0.0, 0.0]))[0] @ cv2.Rodrigues(np.array([0.0, ry, 0.0]))[0])[0].ravel()
    cams = {}
    for view, ry in (("c922", 0.5), ("usb", -0.7)):
        r = rvec(ry)
        cams[view] = {"f": 1500.0, "k1": -0.05, "rx": r[0], "ry": r[1], "rz": r[2], "tx": 0.1, "ty": 0.2, "tz": 6.0}
    return ArmModel(kin=dict(KIN), cams=cams)


def test_fk_matches_hand_computed_poses():
    m = ArmModel(kin=dict(KIN))
    pose = fk(m, {"base": 1500, "shoulder": 1500, "elbow": 1500})
    assert pose.shape == (3, 3)
    assert np.allclose(pose[0], 0)
    assert np.allclose(pose[2], (0.05 + 1 + 1.8, 0.1, 0.2))
    up = fk(m, {"base": 1500, "shoulder": 1500 + np.pi / 2 / 0.001, "elbow": 1500})
    assert np.allclose(up[1], (0.05, 0, 1), atol=1e-9)


def test_project_then_triangulate_returns_the_point():
    m = synthetic_model()
    point = np.array([0.3, -0.2, 0.5])
    tips = {view: tuple(project(m, view, [point])[0]) for view in m.cams}
    assert np.linalg.norm(triangulate(m, tips) - point) < 1e-6
    assert triangulate(m, {"c922": tips["c922"]}) is None


def test_workspace_covers_the_bounds_grid():
    bounds = {"base": (1200, 1400), "shoulder": (1400, 1500), "elbow": (2000, 2100)}
    points = workspace(NOMINAL, bounds)
    assert points.shape == (5 * 3 * 3, 3)
    assert np.isfinite(points).all()


def test_json_round_trip():
    m = synthetic_model()
    m.mm_per_unit, m.table = 105.0, {"point": [0, 0, -0.7], "normal": [0, 0, 1]}
    back = from_json(to_json(m))
    assert back == m
    assert chain(back, {"base": 1500, "shoulder": 1500, "elbow": 1500})[0][2] == -0.7 * 105


def look_at(offset, f, k1):
    target = np.mean([fk(ArmModel(kin=TRUE_KIN), p)[2] for p in POSES], axis=0)
    eye = target + offset
    forward = (target - eye) / np.linalg.norm(target - eye)
    right = np.cross(forward, (0.0, 0.0, 1.0))
    right /= np.linalg.norm(right)
    R = np.array([right, np.cross(forward, right), forward])
    r, t = cv2.Rodrigues(R)[0].ravel(), -R @ eye
    return dict(zip(("f", "k1", "rx", "ry", "rz", "tx", "ty", "tz"), (f, k1, *r, *t)))


CAMS_A = {"c922": look_at((3.0, 0.5, 2.0), 1400.0, -0.05), "usb": look_at((-0.5, 3.5, 0.3), 1100.0, -0.15)}
CAMS_B = {"c922": look_at((2.5, -1.5, 1.5), 1300.0, -0.02), "usb": look_at((0.5, 3.0, 1.2), 1000.0, -0.1)}


def scan_of(cams, seed, outliers=3):
    model, rng = ArmModel(kin=dict(TRUE_KIN), cams=cams), np.random.default_rng(seed)
    samples = [{"pulses": dict(p), "tip": {v: (project(model, v, [fk(model, p)[2]])[0] + rng.normal(0, 0.5, 2)).tolist()
                                           for v in cams}, "t": 0.0} for p in POSES]
    for i in rng.choice(len(samples), outliers, replace=False):
        samples[i]["tip"]["usb"][0] += 100.0
    return samples


def tip_error(kin):
    return np.mean([np.linalg.norm(fk(ArmModel(kin=kin), p)[2] - fk(ArmModel(kin=TRUE_KIN), p)[2]) for p in POSES])


def test_lm_fits_a_curve_and_resists_outliers():
    t = np.linspace(0, 4, 40)
    truth = np.array([800.0, -0.7, 300.0])
    y = truth[0] * np.exp(truth[1] * t) + truth[2] + np.random.default_rng(0).normal(0, 1.0, t.size)
    y[[5, 17, 30]] += (80.0, -60.0, 90.0)
    x, info = levenberg_marquardt(lambda p: p[0] * np.exp(p[1] * t) + p[2] - y, np.array([300.0, -0.2, 0.0]))
    assert info["converged"] and set(info) == {"cost", "iterations", "converged"}
    assert np.all(np.abs(x / truth - 1) < 0.01)


def test_fit_recovers_a_synthetic_arm_from_nominal_start():
    fitted = fit({"arm": scan_of(CAMS_A, seed=0)})
    assert fitted["ok"]
    for gain in ("g_base", "g_shoulder", "g_elbow"):
        assert abs(fitted["kin"][gain] / TRUE_KIN[gain] - 1) < 0.03
    assert max(fitted["rms_px"]["arm"].values()) < 1.0
    assert fitted["rms_px_all"]["arm"]["usb"] > 10.0
    assert len(fitted["starts"]) == 24


def test_fit_shares_kinematics_across_camera_setups():
    a, b = scan_of(CAMS_A, seed=1), scan_of(CAMS_B, seed=2)
    both = fit({"a": a, "b": b})
    assert both["ok"] and set(both["cams"]) == {"a", "b"}
    assert model_for(both, "b").cams == both["cams"]["b"]
    assert tip_error(both["kin"]) <= tip_error(fit({"a": a})["kin"])


def test_fit_rejects_impossible_data_instead_of_returning_nan():
    samples = [{"pulses": dict(p), "tip": {"c922": [700.0, 400.0], "usb": [700.0, 400.0]}, "t": 0.0} for p in POSES]
    assert fit({"flat": samples})["ok"] is False
    assert holdout(samples)["ok"] is False


def test_holdout_reports_model_and_atlas_errors_per_view():
    report = holdout(scan_of(CAMS_A, seed=3, outliers=0))
    assert set(report["per_fold"]) == set(SCAN_GRID["base"])
    for view in ("c922", "usb"):
        assert set(report["model_px"][view]) == set(report["atlas_px"][view]) == {"median", "p90"}
        assert report["model_px"][view]["median"] < 1.5
        assert report["model_px"][view]["median"] < report["atlas_px"][view]["median"]


def marker_corners(model, side=0.5, z=0.2):
    square = np.array([[0, 0, z], [side, 0, z], [side, side, z], [0, side, z]], float)
    return {view: project(model, view, square) for view in model.cams}


def test_scale_from_marker_recovers_mm_per_unit():
    scale = scale_from_marker(synthetic_model(), marker_corners(synthetic_model()))
    assert abs(scale["mm_per_unit"] - 100.0) < 1e-3
    assert scale["side_spread_mm"] < 1e-3


def test_table_normal_is_perpendicular_to_the_marker():
    table = scale_from_marker(synthetic_model(), marker_corners(synthetic_model()))["table"]
    assert np.allclose(table["normal"], (0, 0, 1), atol=1e-6)
    assert np.allclose(table["point"], (0.25, 0.25, 0.2), atol=1e-6)


def test_tip_error_mm_is_zero_for_a_perfect_model():
    model = synthetic_model()
    model.mm_per_unit = 105.0
    samples = [{"pulses": p, "tip": {v: project(model, v, [fk(model, p)[2]])[0].tolist() for v in model.cams}} for p in POSES]
    error = tip_error_mm(model, samples)
    assert error["median"] < 1e-3 and error["p90"] < 1e-3


def test_tip_error_mm_without_a_pair_is_none():
    model = synthetic_model()
    model.mm_per_unit = 105.0
    assert tip_error_mm(model, [{"pulses": POSES[0], "tip": {"c922": [1.0, 2.0], "usb": None}}]) == {"median": None, "p90": None}


def test_holdout_errors_accepts_the_list_tips_of_look_and_predict_tip():
    model = synthetic_model()
    model.mm_per_unit = 105.0
    sample = lambda p: {"pulses": p, "tip": {v: project(model, v, [fk(model, p)[2]])[0].tolist() for v in model.cams}}
    atlas = [sample(p) for p in POSES]
    seen = [sample(POSES[1]), sample(POSES[7])]
    seen[1]["tip"]["usb"] = None
    result = holdout_errors(model, atlas, seen)
    assert result["model_px"]["c922"]["median"] < 1e-6 and result["atlas_px"]["c922"]["median"] < 1e-6
    assert result["model_px"]["usb"]["median"] < 1e-6
    assert result["mm"]["median"] < 1e-3
    model.mm_per_unit = None
    assert holdout_errors(model, atlas, seen)["mm"] is None
