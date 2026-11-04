"""Aplicación web local. Solo escucha en 127.0.0.1 y no tiene ningún camino hacia actuadores."""
import os
import asyncio
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import arm_model, grasp_policy, jetson as jetson_link
from .arm_session import LIMITS_US
from .cell import hardware_gaps, load_cell
from .evaluation import evaluate
from .evidence import RunStore, new_run_id
from .meta import BudgetExceeded, MetaClient, MetaError, MetaPlanner, MetaReference, client_from_env
from .models import Mode
from .planner import FixturePlanner, build_kit_plan, request_assignments
from .scenarios import fixture_path, record_fixture, replay_run, run_scenario
from .sim import REQUIRED_REPLAYS, SCENARIOS, SimMotion, SimWorld, simulated_reference
from .validator import PlanRejected, validate_plan
from .teaching import PoseNotReady, load_poses, pose_blockers, record_pose
from .meta_probe import verified_access
from .arm_vision import latest_analysis
from .scene_vision import (analyze_scene, apply_gripper_selection, latest_scene, load_capture,
                           save_scene, segment_gripper_region)
from .perception import quality_metrics
from .workspace import ImageRegion, latest_proposal, latest_workspace, save_workspace
from .camera_preview import CameraPreview

PROJECT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
DEFAULT_REQUEST = "Coloca la pieza A a la izquierda, B en el centro y C a la derecha; comprueba que estén las tres."
STOP_DESCRIPTION = ("Parada de software: impide nuevas órdenes y cancela la orden simulada. "
                    "No es un paro de emergencia y no corta la alimentación.")
MOTION_DETAIL = "La web nunca mueve el brazo; el brazo real solo se mueve desde la terminal."


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: str
    mode: Mode
    request_text: str = Field(max_length=500)
    use_meta: bool = False
    assignments: dict[str, str] | None = None
    decision_method: Literal["A2", "A3"] = "A2"


class PoseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60)
    expected: dict[str, int] = Field(min_length=6, max_length=6)
    operator_observed: Literal[True]


class WorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    capture_file: str = Field(max_length=100)
    capture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: ImageRegion
    destination: ImageRegion
    operator_observed: Literal[True]


class PreviewStopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    token: str = Field(pattern=r"^[0-9a-f]{32}$")


class GripperSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    capture_file: str = Field(max_length=100)
    capture_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    region: ImageRegion


@dataclass
class RunHandle:
    store: RunStore
    engine: object = None
    stop_requested: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)
    done: threading.Event = field(default_factory=threading.Event)

    def bind(self, engine):
        with self.lock:
            self.engine = engine
            if self.stop_requested:
                engine.request_stop("Parada de software solicitada por el operador.")

    def stop(self):
        with self.lock:
            self.stop_requested = True
            if self.engine is not None:
                self.engine.request_stop("Parada de software solicitada por el operador.")


def _last(events, kind, **match):
    found = [e for e in events if e["event"] == kind and all(e.get(k) == v for k, v in match.items())]
    return found[-1] if found else None


def _step_view(step: dict, events: list[dict]) -> dict:
    view = dict(step, images={}, outcome=None, reasons=[], attempts=0, a2=None, a3=None)
    target = step.get("target_step_id", step["step_id"])
    phases = ("inspect",) if step["action"] == "inspect_scene" else ("post",)
    decision = next((e for e in reversed(events) if e["event"] == "decision" and e["step_id"] == target
                     and e["phase"] in phases), None)
    if decision:
        view.update(outcome=decision["verdict"], reasons=decision["reasons"], attempts=decision["attempt"],
                    failure_class=decision["failure_class"])
    observed = next((e for e in reversed(events) if e["event"] == "observation" and e["step_id"] == target
                     and e["phase"] in phases), None)
    if observed:
        view["images"]["observed"] = observed["frame_path"]
        view.update(a2=observed["a2"]["outcome"], a3=observed["a3"]["outcome"])
    before = _last(events, "observation", step_id=target, phase="pre")
    if before:
        view["images"]["initial"] = before["frame_path"]
    frozen = _last(events, "contract_frozen", step_id=target)
    if frozen and frozen["reference_path"]:
        view["images"]["reference"] = frozen["reference_path"]
    return view


def run_view(handle: RunHandle) -> dict:
    store = handle.store
    events = list(store.events)
    manifest = store.manifest
    finished = _last(events, "run_finished") if handle.done.is_set() else None
    started = _last(events, "step_started")
    empty = {"requested": {}, "commanded": [], "observed": {}, "uncertainty": []}
    return {"run_id": store.run_id, "mode": store.mode.value, "synthetic": store.synthetic,
            "scenario": manifest.get("scenario"), "request_text": manifest.get("request_text"),
            "planner_source": manifest.get("planner_source"), "reference_source": manifest.get("reference_source"),
            "decision_method": manifest.get("decision_method", "A2"),
            "motion": manifest.get("motion"), "camera": manifest.get("camera"), "replay_of": manifest.get("replay_of"),
            "status": finished["status"] if finished else "running",
            "failure_class": finished["failure_class"] if finished else None,
            "stop_reason": finished["stop_reason"] if finished else None,
            "current_step": None if finished or not started else started["step_id"],
            "steps": [_step_view(s, events) for s in manifest.get("plan", {}).get("steps", [])],
            "state": handle.engine.state if handle.engine else empty,
            "api_usage": [e for e in events if e["event"] == "api_usage"],
            "reference_failures": [e["error"] for e in events if e["event"] == "reference_failed"]}

MAX_WORKSPACE_POINTS = 2000
SESSION_GAP_S = 120
INSPECTION = PROJECT / "inspection"
GRASP_PHOTO = r"grasp-(\d{6})-try(\d+)-(descent|lift)-\d{8}\.jpg"
PHOTO_RUN_S = 600
BENCH_TZ = timezone(timedelta(hours=-5))  # Photo names use the bench clock (Lima, no daylight saving).


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _ok_commands(root: Path) -> list[dict]:
    path = root / "real/autonomy/commands.jsonl"
    commands = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        try:
            command = json.loads(line)
            if command["reply"]["ok"]:
                commands.append(dict(command, id=command["reply"]["id"], pulses=command["reply"]["positions"]))
        except (ValueError, KeyError, TypeError):
            continue
    return commands


def _sessions(commands: list[dict]) -> list[list[dict]]:
    sessions: list[list[dict]] = []
    for command in commands:
        if not sessions or command["id"] <= sessions[-1][-1]["id"] or command["t"] - sessions[-1][-1]["t"] > SESSION_GAP_S:
            sessions.append([])
        sessions[-1].append(command)
    return sessions


def _run_starts(folder: Path) -> list[tuple[str, float]]:
    starts = []
    for path in sorted(folder.glob("*.json")):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
            starts.append((run["run_id"], datetime.fromisoformat(run["started_at"]).timestamp()))
        except (ValueError, KeyError, TypeError):
            continue
    return starts


def _attempt_photos(grasps: list[dict]) -> list[list[str]]:
    # A photo is named by the local start time of its grasp run and the try number inside that run.
    photos: dict[tuple[str, int], list[str]] = {}
    for path in sorted(INSPECTION.glob("grasp-*.jpg")):
        if match := re.fullmatch(GRASP_PHOTO, path.name):
            photos.setdefault((match[1], int(match[2])), []).append(path.name)
    starts = {run: int(run[:2]) * 3600 + int(run[2:4]) * 60 + int(run[4:]) for run, _ in photos}
    tries: dict[tuple[str, int], int] = {}
    found = []
    for attempt in grasps:
        t = int(attempt["t"])
        moment = datetime.fromtimestamp(t, BENCH_TZ)
        since = {run: (moment.hour * 3600 + moment.minute * 60 + moment.second - start) % 86400
                 for run, start in starts.items()}
        run = min(since, key=since.get, default=None)
        if run is None or since[run] > PHOTO_RUN_S:
            found.append([])
            continue
        key = (run, t - since[run])
        tries[key] = tries.get(key, 0) + 1
        found.append(photos.get((run, tries[key]), []))
    return found


def _workspace_points(model, bounds) -> list[list[float]]:
    points = arm_model.workspace(model, bounds)
    points = points[::-(-len(points) // MAX_WORKSPACE_POINTS)]
    return (points * (model.mm_per_unit or 1)).tolist()


def create_app(root: str | Path = PROJECT / "runs", pace_s: float = 0.5) -> FastAPI:
    root = Path(root)
    cell = load_cell(PROJECT / "config" / "sim_cell.json")
    physical_cell = load_cell(PROJECT / "config" / "cell.json")
    jetson_host = os.environ.get("PREMONITION_JETSON_HOST", "jetson-usb")
    runs: dict[str, RunHandle] = {}
    jetson_state: dict = {"checked": False, "host": jetson_host}
    last_capture: dict = {}
    saved_scene = latest_scene(root)
    if saved_scene is not None:
        try:
            _, saved_image, saved_frame = load_capture(root, saved_scene["capture"])
            last_capture.update(saved_frame, quality=quality_metrics(saved_image), restored=True)
        except (OSError, ValueError):
            pass
    active: list[RunStore] = []
    pending_usage: list[dict] = []
    execution_lock = threading.Lock()
    teaching_lock = threading.Lock()
    camera_lock = threading.Lock()
    scene_lock = threading.Lock()
    preview_lock = threading.Lock()
    preview_session = None
    controller_reading = None

    def log_usage(entry: dict):
        if active:
            active[-1].log("api_usage", **entry)
        else:
            pending_usage.append(entry)

    meta = client_from_env(on_usage=log_usage)
    app = FastAPI(title="Premonition Lab", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    def launch(body: RunRequest, plan, planner_source: str) -> str:
        scenario = SCENARIOS[body.scenario]
        label = f"replay-{scenario.name}" if body.mode == Mode.REPLAY else scenario.name
        store = RunStore(root, new_run_id(label), body.mode, synthetic=True)
        handle = RunHandle(store)
        runs[store.run_id] = handle
        active[:] = [store]
        for entry in pending_usage:
            store.log("api_usage", **entry)
        pending_usage.clear()

        def work():
            try:
                if body.mode == Mode.REPLAY:
                    source = record_fixture(root, scenario.name, cell, FixturePlanner().plan(DEFAULT_REQUEST, cell))
                    replay_run(source, cell, root, store=store, on_engine=handle.bind)
                else:
                    world = SimWorld(scenario, cell)
                    reference = MetaReference(meta) if body.use_meta else simulated_reference
                    run_scenario(scenario, cell, plan, root, reference=reference, world=world,
                                 motion=SimMotion(world, delay_s=pace_s), request_text=body.request_text,
                                 planner_source=planner_source, reference_source=getattr(
                                     reference, "source", "fixture_simulado"),
                                 store=store, on_engine=handle.bind, decision_method=body.decision_method,
                                 expected_assignments=(body.assignments if body.assignments is not None else
                                                       request_assignments(body.request_text, cell)))
            except Exception as failure:
                store.log("run_finished", status="stopped", failure_class="internal_error", stop_reason=str(failure))
                store.write_manifest(status="stopped", failure_class="internal_error", stop_reason=str(failure))
            finally:
                active.clear()
                execution_lock.release()
                handle.done.set()

        threading.Thread(target=work, daemon=True).start()
        return store.run_id

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/calibration")
    def calibration_page():
        return FileResponse(STATIC / "calibration.html")

    @app.get("/autonomy")
    def autonomy_page():
        return FileResponse(STATIC / "autonomy.html")

    @app.get("/api/autonomy/latest")
    def autonomy_latest():
        runs = sorted((root / "real/autonomy").glob("*.json"))
        return {"run": json.loads(runs[-1].read_text(encoding="utf-8")) if runs else None}

    @app.get("/api/autonomy/latest.jpg")
    def autonomy_latest_image():
        path = root / "real/autonomy/latest.jpg"
        if not path.exists():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/api/autonomy/runs/{run_id}")
    def autonomy_run(run_id: str):
        path = root / "real/autonomy" / f"{run_id}.json"
        if not re.fullmatch(r"[\w.-]+", run_id) or not path.is_file():
            raise HTTPException(404)
        return json.loads(path.read_text(encoding="utf-8"))

    def current_model():
        saved = _read_json(root / "real/calibration/arm_model.json")
        return arm_model.from_json(saved) if saved else arm_model.NOMINAL

    @app.get("/api/arm/model")
    def arm_model_view():
        calibration = root / "real/calibration"
        model = current_model()
        atlas = (_read_json(calibration / "capabilities.json") or {}).get("atlas", [])
        scanned = []
        if atlas:
            bounds = {j: (min(a["pulses"][j] for a in atlas), max(a["pulses"][j] for a in atlas))
                      for j in ("base", "shoulder", "elbow")}
            scanned = _workspace_points(model, bounds)
        limits = _workspace_points(model, {j: LIMITS_US[j] for j in ("base", "shoulder", "elbow")})
        report = _read_json(calibration / "arm_model_fit_report.json")
        return {"nominal": model.nominal, "units": "mm" if model.mm_per_unit is not None else "model",
                "atlas": [arm_model.chain(model, a["pulses"])[3] for a in atlas],
                "workspace": {"scanned": scanned, "limits": limits},
                "table": model.table, "fit": report["summary"] if report else None}

    @app.get("/api/arm/sessions")
    def arm_sessions():
        starts = _run_starts(root / "real/autonomy")
        return [{"index": i, "start": s[0]["t"], "end": s[-1]["t"], "moves": len(s),
                 "runs": [run_id for run_id, started in starts if s[0]["t"] - SESSION_GAP_S <= started <= s[-1]["t"]]}
                for i, s in enumerate(_sessions(_ok_commands(root)))]

    @app.get("/api/arm/replay/{index}")
    def arm_replay(index: int):
        sessions = _sessions(_ok_commands(root))
        if not 0 <= index < len(sessions):
            raise HTTPException(404, "Unknown session.")
        model = current_model()
        return {"keyframes": [{"t": c["t"], "duration": c["duration"], "pulses": c["pulses"],
                               "chain": arm_model.chain(model, c["pulses"])} for c in sessions[index]]}

    @app.get("/api/arm/live")
    def arm_live():
        commands = _ok_commands(root)
        if not commands:
            return {"pulses": None}
        last = commands[-1]
        return {"t": last["t"], "pulses": last["pulses"], "chain": arm_model.chain(current_model(), last["pulses"]),
                "age_s": time.time() - last["t"]}

    @app.get("/api/arm/learning")
    def arm_learning():
        memory = grasp_policy.upgrade_memory(_read_json(root / "real/calibration/skill_memory.json") or {})
        arms = []
        for arm in grasp_policy.ARMS:
            (alpha, beta), (alpha0, beta0) = grasp_policy.posterior(memory["attempts"], arm), grasp_policy.posterior([], arm)
            arms.append({"params": asdict(arm), "rate": alpha / (alpha + beta), "attempts": int(alpha + beta - alpha0 - beta0),
                         "successes": int(alpha - alpha0), "alpha": alpha, "beta": beta})
        return {"arms": sorted(arms, key=lambda a: -a["rate"])}

    @app.get("/api/arm/attempts")
    def arm_attempts():
        memory = grasp_policy.upgrade_memory(_read_json(root / "real/calibration/skill_memory.json") or {})
        grasps = [a for a in memory["attempts"] if not a.get("legacy") and a.get("skill", "grasp") == "grasp"]
        return {"attempts": [{"t": a["t"], "class": a["class"], "params": a["params"], "seconds": a.get("seconds"),
                              "reach": a.get("reach") if a["class"] == "reach_failed" else None,
                              "descent_stop": a.get("descent_stop"), "photos": photos}
                             for a, photos in zip(grasps[:-11:-1], _attempt_photos(grasps)[:-11:-1])]}

    @app.get("/api/arm/photos/{name}")
    def attempt_photo(name: str):
        path = INSPECTION / name
        if not re.fullmatch(GRASP_PHOTO, name) or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/jpeg")

    def teaching_status():
        reference_path = PROJECT / "config" / "reference_poses.json"
        references = json.loads(reference_path.read_text(encoding="utf-8")) if reference_path.exists() else None
        return {"jetson": jetson_state, "controller": controller_reading,
                "pose_blockers": pose_blockers(controller_reading, physical_cell),
                "capture": last_capture, "poses": load_poses(root),
                "motion_enabled": False, "stop_procedure_confirmed": physical_cell.stop_procedure_confirmed,
                "meta_configured": meta is not None,
                "meta_verified": verified_access(root, meta.api_key if meta else None),
                "vision_analysis": latest_analysis(root),
                "scene_analysis": latest_scene(root),
                "workspace_regions": latest_workspace(root),
                "workspace_proposal": latest_proposal(root),
                "meta_setup_command": f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{PROJECT / "tools" / "configure-meta-key.ps1"}"',
                "reference_poses": references,
                "note": "Pose recording only. This page does not energize or move the arm."}

    @app.get("/api/calibration")
    def calibration_status():
        return teaching_status()

    @app.post("/api/calibration/inspect")
    def inspect_for_teaching():
        nonlocal controller_reading
        if not teaching_lock.acquire(blocking=False):
            raise HTTPException(409, "An arm check or pose recording is already in progress.")
        try:
            jetson_state.update(jetson_link.check_connection(jetson_host), checked=True)
            if not jetson_state.get("connected"):
                controller_reading = None
                raise HTTPException(503, "Jetson unavailable. Check USB and SSH.")
            try:
                controller_reading = jetson_link.read_commanded_pulses(jetson_host)
            except (jetson_link.JetsonError, OSError, ValueError, jetson_link.subprocess.TimeoutExpired):
                controller_reading = None
                raise HTTPException(503, "Controller unavailable. Check the I2C connection.") from None
            return teaching_status()
        finally:
            teaching_lock.release()

    @app.post("/api/calibration/poses")
    def save_taught_pose(body: PoseRequest):
        nonlocal controller_reading
        if not teaching_lock.acquire(blocking=False):
            raise HTTPException(409, "An arm check or pose recording is already in progress.")
        try:
            if controller_reading is None:
                raise HTTPException(409, "Check the arm before recording a pose.")
            try:
                first = jetson_link.read_commanded_pulses(jetson_host)
                time.sleep(0.15)
                second = jetson_link.read_commanded_pulses(jetson_host)
                controller_reading = second
                pose = record_pose(root, physical_cell, body.name, body.expected, first, second, body.operator_observed)
            except PoseNotReady as failure:
                raise HTTPException(409, str(failure)) from None
            except (jetson_link.JetsonError, OSError, ValueError, jetson_link.subprocess.TimeoutExpired):
                controller_reading = None
                raise HTTPException(503, "Could not record the pose. Check the controller again.") from None
            return {"pose": pose, "status": teaching_status()}
        finally:
            teaching_lock.release()

    @app.get("/api/status")
    def status():
        return {"default_mode": Mode.SIMULATION.value,
                "motion": {"enabled": False, "detail": MOTION_DETAIL},
                "meta": {"configured": meta is not None,
                         "detail": ("clave configurada; acceso sin comprobar" if meta else
                                    "sin clave: el planificador y la referencia son fixtures")},
                "jetson": jetson_state, "capture": last_capture, "hardware_gaps": hardware_gaps(physical_cell),
                "stop_description": STOP_DESCRIPTION, "default_request": DEFAULT_REQUEST,
                "scenarios": [{"name": s.name, "title": s.title, "description": s.description,
                               "required_replay": s.name in REQUIRED_REPLAYS} for s in SCENARIOS.values()]}

    @app.post("/api/jetson/check")
    def jetson_check():
        jetson_state.update(jetson_link.check_connection(jetson_host), checked=True)
        return jetson_state

    @app.post("/api/camera/capture")
    def camera_capture():
        nonlocal last_capture
        if not camera_lock.acquire(blocking=False):
            raise HTTPException(409, "The camera is already taking a photo.")
        try:
            last_capture = jetson_link.capture_to_disk(jetson_host, root)
            return dict(last_capture)
        except (jetson_link.CameraError, OSError, jetson_link.subprocess.TimeoutExpired) as failure:
            raise HTTPException(502, f"La cámara no respondió: {failure}") from failure
        finally:
            camera_lock.release()

    @app.get("/api/camera/live.mjpg")
    def live_preview(token: str):
        nonlocal preview_session
        if not re.fullmatch(r"[0-9a-f]{32}", token):
            raise HTTPException(422, "Invalid preview token.")
        with preview_lock:
            if preview_session is not None and not preview_session.done.is_set():
                raise HTTPException(409, "A live preview is already open.")
            try:
                session = CameraPreview(jetson_host, token, camera_lock)
            except (jetson_link.CameraError, OSError) as failure:
                raise HTTPException(409, str(failure)) from failure
            preview_session = session

        async def frames():
            sequence = 0
            try:
                while True:
                    frame = await asyncio.to_thread(session.next_frame, sequence)
                    if frame is None:
                        if session.done.is_set():
                            break
                        continue
                    sequence, jpeg = frame
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                           + str(len(jpeg)).encode() + b"\r\nX-Sequence: " + str(sequence).encode()
                           + b"\r\n\r\n" + jpeg + b"\r\n")
            finally:
                session.request_stop()
        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store, no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/camera/live/status")
    def live_status():
        with preview_lock:
            return preview_session.status() if preview_session is not None else {"running": False, "active": False, "frames": 0}

    @app.post("/api/camera/live/stop")
    def stop_live(body: PreviewStopRequest):
        with preview_lock:
            if preview_session is None:
                return {"running": False, "active": False}
            if body.token != preview_session.token:
                raise HTTPException(409, "That preview belongs to another tab.")
            try:
                preview_session.stop()
            except jetson_link.CameraError as failure:
                raise HTTPException(503, str(failure)) from failure
            return preview_session.status()

    @app.post("/api/calibration/analyze-scene")
    def inspect_scene():
        if meta is None:
            raise HTTPException(409, "Configure the Meta API key before analyzing the scene.")
        if not scene_lock.acquire(blocking=False):
            raise HTTPException(409, "Scene analysis is already running.")
        usage = []
        try:
            capture = dict(camera_capture())
            observer = MetaClient(meta.api_key, meta.budget, http=meta.http, on_usage=usage.append)
            report = analyze_scene(observer, root, capture)
            report["api_usage"] = usage
            save_scene(root, report)
            return {"report": report, "status": teaching_status()}
        except (MetaError, ValueError, OSError) as failure:
            raise HTTPException(502, f"Scene analysis failed: {str(failure).replace(meta.api_key, '<key>')}") from failure
        except BudgetExceeded as failure:
            raise HTTPException(429, str(failure)) from failure
        finally:
            scene_lock.release()

    @app.post("/api/calibration/workspace")
    def record_workspace(body: WorkspaceRequest):
        capture = dict(last_capture)
        if capture.get("file") != body.capture_file or capture.get("sha256") != body.capture_sha256:
            raise HTTPException(409, "The photo changed. Mark the areas on the current photo.")
        try:
            report = save_workspace(root, capture, body.source, body.destination)
        except (ValueError, OSError) as failure:
            raise HTTPException(422, str(failure)) from failure
        return {"workspace": report, "status": teaching_status()}

    @app.post("/api/calibration/select-gripper")
    def select_gripper(body: GripperSelectionRequest):
        if meta is None:
            raise HTTPException(409, "Configure the Meta API key before using SAM.")
        if not scene_lock.acquire(blocking=False):
            raise HTTPException(409, "Scene analysis is already running.")
        try:
            parent = latest_scene(root)
            capture = dict(last_capture)
            if (parent is None or capture.get("file") != body.capture_file
                    or capture.get("sha256") != body.capture_sha256
                    or parent["capture"]["file"] != body.capture_file
                    or parent["capture"]["sha256"] != body.capture_sha256):
                raise HTTPException(409, "Analyze the current photo before selecting the gripper.")
            usage = []
            observer = MetaClient(meta.api_key,meta.budget,http=meta.http,on_usage=usage.append)
            objects, box = segment_gripper_region(observer,root,parent,body.region.model_dump())
            report = apply_gripper_selection(parent,objects,box,usage)
            save_scene(root,report)
            return {"report":report,"status":teaching_status()}
        except BudgetExceeded as failure:
            raise HTTPException(429,str(failure)) from failure
        except (MetaError,ValueError,OSError) as failure:
            raise HTTPException(502,str(failure).replace(meta.api_key,"<key>")) from failure
        finally:
            scene_lock.release()

    @app.get("/api/captures/{name}")
    def capture_file(name: str):
        path = root / "real" / "captures" / name
        if not re.fullmatch(r"[\w.-]+\.jpg", name) or not path.exists():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/api/runs")
    def create_run(body: RunRequest):
        if body.scenario not in SCENARIOS:
            raise HTTPException(404, f"Escenario desconocido: {body.scenario}")
        if not execution_lock.acquire(blocking=False):
            raise HTTPException(409, "Ya hay una ejecución en curso.")
        handed_off = False
        try:
            if body.use_meta and (meta is None or body.mode == Mode.REPLAY):
                raise HTTPException(409, "Meta necesita modo simulación y la variable MODEL_API_KEY.")
            if body.mode == Mode.REPLAY:
                run_id = launch(body, None, "registro")
                handed_off = True
                return {"run_id": run_id}
            expected = body.assignments if body.assignments is not None else request_assignments(body.request_text, cell)
            if set(expected) != {p.id for p in cell.pieces}:
                raise PlanRejected(["el objetivo debe asignar todas las piezas del kit"])
            approved = build_kit_plan(expected, cell)
            issues = validate_plan(approved, cell, expected)
            if issues:
                raise PlanRejected(issues)
            planner = MetaPlanner(meta) if body.use_meta else FixturePlanner()
            text = body.request_text
            if body.assignments is not None:
                text = f"Objetivo aprobado (IDs pieza/destino): {expected}. Contexto: {body.request_text}"
            plan = planner.plan(text, cell) if body.use_meta or body.assignments is None else approved
            issues = validate_plan(plan, cell, expected)
            if issues:
                raise PlanRejected(issues)
            run_id = launch(body, plan, planner.source)
            handed_off = True
            return {"run_id": run_id}
        except PlanRejected as rejected:
            raise HTTPException(422, "; ".join(rejected.issues)) from rejected
        except (MetaError, BudgetExceeded) as failure:
            raise HTTPException(502, str(failure)) from failure
        finally:
            if not handed_off:
                pending_usage.clear()
                execution_lock.release()

    @app.get("/api/runs")
    def list_runs():
        return [{"run_id": run_id, "status": run_view(h)["status"], "mode": h.store.mode.value}
                for run_id, h in runs.items()]

    def handle_of(run_id: str) -> RunHandle:
        if run_id not in runs:
            raise HTTPException(404, "Ejecución desconocida.")
        return runs[run_id]

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        return run_view(handle_of(run_id))

    @app.post("/api/runs/{run_id}/stop")
    def stop_run(run_id: str):
        handle_of(run_id).stop()
        return {"detail": STOP_DESCRIPTION}

    @app.get("/api/runs/{run_id}/files/{path:path}")
    def run_file(run_id: str, path: str):
        base = handle_of(run_id).store.path.resolve()
        target = (base / path).resolve()
        allowed = (base / "frames", base / "references")
        if not any(target.is_relative_to(folder) for folder in allowed) or not target.is_file():
            raise HTTPException(404)
        return FileResponse(target, media_type="image/jpeg")

    @app.post("/api/evaluation")
    def evaluation():
        if not execution_lock.acquire(blocking=False):
            raise HTTPException(409, "Ya hay una ejecución o evaluación en curso.")
        try:
            plan = FixturePlanner().plan(DEFAULT_REQUEST, cell)
            for name in SCENARIOS:
                record_fixture(root, name, cell, plan)
            return evaluate([fixture_path(root, name) for name in SCENARIOS], cell)
        finally:
            execution_lock.release()

    return app
