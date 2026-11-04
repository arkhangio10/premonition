"""Planar kinematic chain plus pinhole cameras: pulses to the 3D gripper tip and to pixels in both views."""
from dataclasses import dataclass, field

import cv2
import numpy as np

from .atlas import predict_tip
from .view_check import TABLE_MARKER_MM

PP = (960.0, 540.0)
Z_BASE = Z_ELBOW = 1500
L2 = 1.0
KINEMATIC = ("g_base", "g_shoulder", "g_elbow", "z_shoulder", "a1", "u", "v", "d")
CAMERA = ("f", "k1", "rx", "ry", "rz", "tx", "ty", "tz")
TABLE_Z = -0.7
PRIORS = {"g_base": (1.466e-3, 2.2e-4), "g_shoulder": (1.571e-3, 3.1e-4), "g_elbow": (1.571e-3, 3.1e-4)}
STARTS = [(s, e, z, f) for s in (1, -1) for e in (1, -1) for z in (1200, 1500, 1800) for f in (1000.0, 1500.0)]
SCREEN_ITER = 20
F_RANGE = (400.0, 4000.0)
INLIER_PX = 15.0


@dataclass
class ArmModel:
    kin: dict[str, float]
    cams: dict[str, dict[str, float]] = field(default_factory=dict)
    mm_per_unit: float | None = None
    table: dict | None = None
    nominal: bool = False


NOMINAL = ArmModel(
    kin={"g_base": np.pi / 2000, "g_shoulder": np.pi / 2000, "g_elbow": -np.pi / 2000, "z_shoulder": 1500,
         "a1": 0.05, "u": 1.8, "v": 0.0, "d": 0.0},
    mm_per_unit=105, nominal=True)


def fk(model, pulses) -> np.ndarray:
    k = model.kin
    tb = k["g_base"] * (pulses["base"] - Z_BASE)
    ts = k["g_shoulder"] * (pulses["shoulder"] - k["z_shoulder"])
    te = k["g_elbow"] * (pulses["elbow"] - Z_ELBOW)
    elbow = np.array([k["a1"] + L2 * np.cos(ts), L2 * np.sin(ts)])
    c, s = np.cos(ts + te), np.sin(ts + te)
    tip = elbow + (k["u"] * c - k["v"] * s, k["u"] * s + k["v"] * c)
    cb, sb = np.cos(tb), np.sin(tb)
    zero = np.zeros_like(tb)
    return np.array([[zero, zero, zero],
                     [elbow[0] * cb, elbow[0] * sb, elbow[1]],
                     [tip[0] * cb - k["d"] * sb, tip[0] * sb + k["d"] * cb, tip[1]]])


def chain(model, pulses) -> list[list[float]]:
    shoulder, elbow, tip = fk(model, pulses)
    if model.table is None:
        foot = np.array([0.0, 0.0, TABLE_Z])
    else:
        point, normal = np.asarray(model.table["point"], float), np.asarray(model.table["normal"], float)
        foot = shoulder - np.dot(shoulder - point, normal) / np.dot(normal, normal) * normal
    points = np.array([foot, shoulder, elbow, tip])
    if model.mm_per_unit is not None:
        points = points * model.mm_per_unit
    return points.tolist()


def _intrinsics(cam):
    return np.array([[cam["f"], 0, PP[0]], [0, cam["f"], PP[1]], [0, 0, 1]]), np.array([cam["k1"], 0, 0, 0])


def _pose(cam):
    return np.array([cam["rx"], cam["ry"], cam["rz"]]), np.array([cam["tx"], cam["ty"], cam["tz"]])


def project(model, view, points) -> np.ndarray:
    cam = model.cams[view]
    K, dist = _intrinsics(cam)
    rvec, tvec = _pose(cam)
    return cv2.projectPoints(np.asarray(points, float).reshape(-1, 3), rvec, tvec, K, dist)[0].reshape(-1, 2)


def triangulate(model, tips: dict) -> np.ndarray | None:
    views = ("c922", "usb")
    if any(v not in tips or v not in model.cams for v in views):
        return None
    projections, normalized = [], []
    for view in views:
        cam = model.cams[view]
        K, dist = _intrinsics(cam)
        rvec, tvec = _pose(cam)
        pixel = np.array(tips[view], float).reshape(1, 1, 2)
        normalized.append((np.linalg.inv(K) @ [*cv2.undistortImagePoints(pixel, K, dist).ravel(), 1.0])[:2])
        projections.append(np.hstack([cv2.Rodrigues(rvec)[0], tvec.reshape(3, 1)]))
    h = cv2.triangulatePoints(projections[0], projections[1], normalized[0].reshape(2, 1), normalized[1].reshape(2, 1))
    return (h[:3] / h[3]).ravel()


def workspace(model, bounds: dict[str, tuple[int, int]], step_us=50) -> np.ndarray:
    axes = [np.arange(lo, hi + 1, step_us) for lo, hi in (bounds[j] for j in ("base", "shoulder", "elbow"))]
    return np.array([fk(model, {"base": b, "shoulder": s, "elbow": e})[2]
                     for b in axes[0] for s in axes[1] for e in axes[2]])


def _triangulate_all(model, points) -> np.ndarray:
    return np.array([triangulate(model, {view: p[i] for view, p in points.items()}) for i in range(len(points["c922"]))])


def scale_from_marker(model, corners: dict, side_mm=TABLE_MARKER_MM) -> dict:
    square = _triangulate_all(model, corners)
    sides = np.linalg.norm(square - np.roll(square, -1, axis=0), axis=1)
    mm_per_unit = side_mm / float(sides.mean())
    normal = np.cross(square[2] - square[0], square[3] - square[1])
    normal = normal / np.linalg.norm(normal) * (1 if normal[2] >= 0 else -1)
    return {"mm_per_unit": mm_per_unit, "side_spread_mm": float(np.ptp(sides)) * mm_per_unit,
            "table": {"point": square.mean(axis=0).tolist(), "normal": normal.tolist()}}


def scale_from_segment(model, ends: dict, length_mm=50.0) -> dict:
    a, b = _triangulate_all(model, ends)
    return {"mm_per_unit": length_mm / float(np.linalg.norm(a - b))}


def tip_error_mm(model, samples) -> dict:
    seen = [(s["pulses"], s["tip"]) for s in samples if all(s["tip"].get(v) is not None for v in ("c922", "usb"))]
    errors = [np.linalg.norm(fk(model, pulses)[2] - triangulate(model, tip)) * model.mm_per_unit for pulses, tip in seen]
    if not errors:
        return {"median": None, "p90": None}
    return {"median": float(np.median(errors)), "p90": float(np.percentile(errors, 90))}


def to_json(model) -> dict:
    return {"kin": dict(model.kin), "cams": {v: dict(c) for v, c in model.cams.items()},
            "mm_per_unit": model.mm_per_unit, "table": model.table, "nominal": model.nominal}


def from_json(data) -> ArmModel:
    return ArmModel(kin=dict(data["kin"]), cams={v: dict(c) for v, c in data["cams"].items()},
                    mm_per_unit=data["mm_per_unit"], table=data["table"], nominal=data["nominal"])


def levenberg_marquardt(residual, x0, max_iter=200, huber_px=5.0) -> tuple[np.ndarray, dict]:
    def robust(r):
        a = np.abs(r)
        return float(np.sum(np.where(a <= huber_px, 0.5 * r ** 2, huber_px * (a - 0.5 * huber_px))))

    x = np.asarray(x0, float)
    r = residual(x)
    cost, lam, converged = robust(r), 1e-3, False
    for iteration in range(1, max_iter + 1):
        h = 1e-6 * np.maximum(np.abs(x), 1e-2)
        J = np.column_stack([(residual(x + e) - residual(x - e)) / (2 * e[i]) for i, e in enumerate(np.diag(h))])
        w = np.minimum(1.0, huber_px / np.maximum(np.abs(r), 1e-12))
        A, g = J.T @ (w[:, None] * J), J.T @ (w * r)
        while lam <= 1e10:
            step = np.linalg.solve(A + lam * np.diag(np.diag(A)), -g)
            trial = robust(r_trial := residual(x + step))
            if trial < cost:
                break
            lam *= 10
        else:
            # No step lowers the cost: a minimum, unless the cost itself is not finite.
            converged = bool(np.isfinite(cost))
            break
        x, r, lam = x + step, r_trial, lam / 10
        converged, cost = cost - trial <= 1e-9 * cost, trial
        if converged:
            break
    return x, {"cost": cost, "iterations": iteration, "converged": converged}


def _layout(datasets):
    layout = []
    for name, samples in datasets.items():
        pulses = {j: np.array([s["pulses"][j] for s in samples], float) for j in ("base", "shoulder", "elbow")}
        views = sorted({v for s in samples for v, tip in s["tip"].items() if tip is not None})
        observed = {v: (np.array([i for i, s in enumerate(samples) if s["tip"].get(v) is not None]),
                        np.array([s["tip"][v] for s in samples if s["tip"].get(v) is not None], float)) for v in views}
        layout.append((name, pulses, observed))
    return layout


def _pack(kin, cams, layout):
    return np.array([kin[k] for k in KINEMATIC]
                    + [cams[name][view][c] for name, _, observed in layout for view in observed for c in CAMERA], float)


def _unpack(x, layout):
    kin, cams, i = dict(zip(KINEMATIC, x.tolist())), {}, len(KINEMATIC)
    for name, _, observed in layout:
        cams[name] = {}
        for view in observed:
            cams[name][view], i = dict(zip(CAMERA, x[i:i + len(CAMERA)].tolist())), i + len(CAMERA)
    return kin, cams


def _residual(layout):
    def residual(x):
        kin, cams = _unpack(x, layout)
        parts = []
        for name, pulses, observed in layout:
            model = ArmModel(kin=kin, cams=cams[name])
            tips = fk(model, pulses)[2].T
            parts += [(project(model, view, tips[idx]) - pixels).ravel() for view, (idx, pixels) in observed.items()]
        parts.append([(abs(kin[g]) - mean) / sigma for g, (mean, sigma) in PRIORS.items()])
        return np.concatenate(parts)
    return residual


def _initial_cams(kin, f, layout):
    K = _intrinsics({"f": f, "k1": 0.0})[0]
    cams = {}
    for name, pulses, observed in layout:
        tips = fk(ArmModel(kin=kin), pulses)[2].T
        cams[name] = {}
        for view, (idx, pixels) in observed.items():
            _, rvec, tvec = cv2.solvePnP(tips[idx], pixels, K, None, flags=cv2.SOLVEPNP_SQPNP)
            cams[name][view] = dict(zip(CAMERA, (f, 0.0, *rvec.ravel().tolist(), *tvec.ravel().tolist())))
    return cams


def _mirror(kin, cams):
    # Negated angles and offsets with every camera turned 180 deg about x give the same pixels, z upside down.
    kin = dict(kin, **{k: -kin[k] for k in ("g_base", "g_shoulder", "g_elbow", "v", "d")})
    turned = {}
    for name, views in cams.items():
        turned[name] = {}
        for view, cam in views.items():
            r = cv2.Rodrigues(cv2.Rodrigues(_pose(cam)[0])[0] @ np.diag([1.0, -1.0, -1.0]))[0].ravel()
            turned[name][view] = dict(cam, rx=float(r[0]), ry=float(r[1]), rz=float(r[2]))
    return kin, turned


def _solve(layout, kin, cams, max_iter=200):
    x, info = levenberg_marquardt(_residual(layout), _pack(kin, cams, layout), max_iter)
    kin, cams = _unpack(x, layout)
    # Canonical solution: raising the shoulder pulse raises the tip, as on the hardware.
    pulses, arm = layout[0][1], ArmModel(kin=kin)
    if np.mean(fk(arm, dict(pulses, shoulder=pulses["shoulder"] + 1))[2][2] - fk(arm, pulses)[2][2]) < 0:
        kin, cams = _mirror(kin, cams)
    ok, rms, rms_all, inliers = bool(np.isfinite(x).all()), {}, {}, {}
    for name, pulses, observed in layout:
        model = ArmModel(kin=kin, cams=cams[name])
        tips = fk(model, pulses)[2].T
        rms[name], rms_all[name], inliers[name] = {}, {}, {}
        for view, (idx, pixels) in observed.items():
            rvec, tvec = _pose(cams[name][view])
            depth = (tips @ cv2.Rodrigues(rvec)[0].T + tvec)[:, 2]
            error = np.linalg.norm(project(model, view, tips[idx]) - pixels, axis=1)
            inlier = error <= INLIER_PX
            rms[name][view] = float(np.sqrt(np.mean(error[inlier] ** 2))) if inlier.any() else float("nan")
            rms_all[name][view] = float(np.sqrt(np.mean(error ** 2)))
            inliers[name][view] = {"n": int(inlier.sum()), "of": len(error)}
            ok = (ok and np.isfinite(rms[name][view]) and depth.min() > 0
                  and F_RANGE[0] <= cams[name][view]["f"] <= F_RANGE[1])
    return {"ok": bool(ok), "cost": info["cost"], "kin": kin, "cams": cams, "rms_px": rms, "rms_px_all": rms_all,
            "inliers": inliers}


def fit(datasets: dict[str, list]) -> dict:
    # Every start gets a short screening run; only the best one is iterated to convergence.
    layout = _layout(datasets)
    # Tips that all fall inside one inlier radius cannot place a camera.
    if any(np.ptp(pixels, axis=0).max() < INLIER_PX for _, _, observed in layout for _, pixels in observed.values()):
        return {"ok": False, "kin": dict(NOMINAL.kin), "cams": {}, "rms_px": {}, "rms_px_all": {}, "inliers": {}, "starts": []}
    runs = []
    for s, e, z, f in STARTS:
        kin = dict(NOMINAL.kin, g_shoulder=s * NOMINAL.kin["g_shoulder"], g_elbow=e * NOMINAL.kin["g_elbow"], z_shoulder=z)
        runs.append((_solve(layout, kin, _initial_cams(kin, f, layout), SCREEN_ITER),
                     {"g_shoulder": s, "g_elbow": e, "z_shoulder": z, "f": f}))
    best = min((run for run, _ in runs), key=lambda run: (not run["ok"], run["cost"]))
    best = _solve(layout, best["kin"], best["cams"])
    return {"ok": best["ok"], "kin": best["kin"], "cams": best["cams"], "rms_px": best["rms_px"],
            "rms_px_all": best["rms_px_all"], "inliers": best["inliers"],
            "starts": [dict(start, cost=run["cost"], ok=run["ok"]) for run, start in runs]}


def model_for(fitted, name) -> ArmModel:
    return ArmModel(kin=dict(fitted["kin"]), cams={v: dict(c) for v, c in fitted["cams"][name].items()})


def _stats(errors):
    return {v: {"median": float(np.median(e)), "p90": float(np.percentile(e, 90))} for v, e in errors.items()}


def holdout(samples: list, by="base") -> dict:
    # Each fold starts from the fit on every sample, not from the full multistart.
    full = fit({"all": samples})
    if not full["ok"]:
        return {"ok": False, "model_px": {}, "atlas_px": {}, "per_fold": {}}
    model_px, atlas_px, per_fold = {}, {}, {}
    for value in sorted({s["pulses"][by] for s in samples}):
        train = [s for s in samples if s["pulses"][by] != value]
        layout = _layout({"all": train})
        fold = _solve(layout, full["kin"], full["cams"])
        model = model_for(fold, "all")
        fold_model, fold_atlas = {}, {}
        for s in (s for s in samples if s["pulses"][by] == value):
            atlas, point = predict_tip(train, s["pulses"]), fk(model, s["pulses"])[2]
            for view, tip in s["tip"].items():
                if tip is not None and view in model.cams:
                    fold_model.setdefault(view, []).append(float(np.linalg.norm(project(model, view, [point])[0] - tip)))
                    fold_atlas.setdefault(view, []).append(float(np.linalg.norm(np.subtract(atlas[view], tip))))
        for view in fold_model:
            model_px.setdefault(view, []).extend(fold_model[view])
            atlas_px.setdefault(view, []).extend(fold_atlas[view])
        per_fold[value] = {"ok": fold["ok"], "model_px": _stats(fold_model), "atlas_px": _stats(fold_atlas)}
    return {"ok": True, "model_px": _stats(model_px), "atlas_px": _stats(atlas_px), "per_fold": per_fold}


def epipolar_report(atlas) -> dict:
    tips = [s["tip"] for s in atlas if s["tip"].get("c922") is not None and s["tip"].get("usb") is not None]
    a, b = (np.array([t[v] for t in tips], float) for v in ("c922", "usb"))
    F, mask = cv2.findFundamentalMat(a, b, cv2.FM_RANSAC, 3.0, 0.99)
    ha, hb = np.hstack([a, np.ones((len(a), 1))]), np.hstack([b, np.ones((len(b), 1))])
    in_b, in_a = ha @ F.T, hb @ F
    algebraic = np.abs(np.sum(hb * in_b, axis=1))
    distance = 0.5 * algebraic * (1 / np.hypot(in_b[:, 0], in_b[:, 1]) + 1 / np.hypot(in_a[:, 0], in_a[:, 1]))
    return {"pairs": len(tips), "inliers": int(mask.sum()), "median": float(np.median(distance)),
            "p90": float(np.percentile(distance, 90)), "max": float(distance.max())}
