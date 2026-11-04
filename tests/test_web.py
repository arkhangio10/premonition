import json
import re
import subprocess
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
REQUEST_TEXT = "Coloca la pieza A a la izquierda, B en el centro y C a la derecha; comprueba que estén las tres."


@pytest.fixture
def forbid_hardware(monkeypatch):
    """Cualquier intento de abrir I²C o lanzar un proceso falla la prueba."""
    calls = []

    def blocked(name):
        def refuse(*args, **kwargs):
            calls.append((name, args))
            raise AssertionError(f"{name} no debe usarse: {args}")
        return refuse

    fake = types.ModuleType("smbus")
    fake.SMBus = blocked("smbus.SMBus")
    monkeypatch.setitem(sys.modules, "smbus", fake)
    monkeypatch.setitem(sys.modules, "smbus2", fake)
    monkeypatch.setattr(subprocess, "Popen", blocked("subprocess.Popen"))
    monkeypatch.setattr(subprocess, "run", blocked("subprocess.run"))
    return calls


@pytest.fixture
def client(tmp_path, monkeypatch):
    from premonition.web import create_app

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    return TestClient(create_app(root=tmp_path, pace_s=0.0), base_url="http://127.0.0.1")


def start(client, scenario="success", mode="simulation", **extra):
    body = {"scenario": scenario, "mode": mode, "request_text": REQUEST_TEXT, **extra}
    response = client.post("/api/runs", json=body)
    assert response.status_code == 200, response.text
    return response.json()["run_id"]


def finished(client, run_id):
    for _ in range(600):
        view = client.get(f"/api/runs/{run_id}").json()
        if view["status"] != "running":
            return view
        time.sleep(0.02)
    raise AssertionError("la ejecución no terminó")


def test_importing_every_module_touches_no_hardware(forbid_hardware):
    import importlib
    import pkgutil

    import premonition

    for module in pkgutil.iter_modules(premonition.__path__):
        if module.name != "__main__":
            importlib.import_module(f"premonition.{module.name}")
    assert forbid_hardware == []


def test_booting_and_querying_status_touches_no_hardware(forbid_hardware, client):
    assert client.get("/").status_code == 200
    assert client.get("/api/status").status_code == 200
    assert forbid_hardware == []


def test_a_full_simulated_run_touches_no_hardware(forbid_hardware, client):
    view = finished(client, start(client))
    assert view["status"] == "completed" and forbid_hardware == []


def test_status_declares_motion_disabled_and_simulation_default(client):
    status = client.get("/api/status").json()
    assert status["default_mode"] == "simulation"
    assert status["motion"]["enabled"] is False
    assert status["meta"] == {"configured": False, "detail": "sin clave: el planificador y la referencia son fixtures"}
    assert status["jetson"]["checked"] is False


def test_status_lists_what_is_missing_for_hardware(tmp_path, monkeypatch, real_cell):
    from premonition import web
    original = web.load_cell
    unconfirmed = real_cell.model_copy(update={"stop_procedure_confirmed": False, "observe_pose": None})
    monkeypatch.setattr(web, "load_cell", lambda p: unconfirmed if Path(p).name == "cell.json" else original(p))
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    client = TestClient(web.create_app(tmp_path), base_url="http://127.0.0.1")
    gaps = " ".join(client.get("/api/status").json()["hardware_gaps"])
    assert "pose de observación" in gaps and "parada física" in gaps


def test_there_is_no_hardware_mode_to_request(client):
    response = client.post("/api/runs", json={"scenario": "success", "mode": "hardware", "request_text": REQUEST_TEXT})
    assert response.status_code == 422


def test_request_cannot_carry_an_enable_flag(client):
    response = client.post("/api/runs", json={"scenario": "success", "mode": "simulation",
                                              "request_text": REQUEST_TEXT, "motion_enabled": True})
    assert response.status_code == 422
    assert client.get("/api/status").json()["motion"]["enabled"] is False


def test_unrecognized_request_shows_the_reason_and_starts_nothing(client):
    response = client.post("/api/runs", json={"scenario": "success", "mode": "simulation", "request_text": "haz algo"})
    assert response.status_code == 422 and "MODEL_API_KEY" in response.json()["detail"]
    assert client.get("/api/runs").json() == []


def test_meta_request_without_key_fails_visibly_instead_of_using_a_fixture(client):
    response = client.post("/api/runs", json={"scenario": "success", "mode": "simulation",
                                              "request_text": REQUEST_TEXT, "use_meta": True})
    assert response.status_code == 409 and "MODEL_API_KEY" in response.json()["detail"]


def test_run_view_is_labelled_as_synthetic(client):
    view = finished(client, start(client))
    assert view["mode"] == "simulation" and view["synthetic"] is True
    assert view["planner_source"] == "fixture_simulado" and view["reference_source"] == "fixture_simulado"
    assert view["motion"] == "simulado" and view["camera"] == "sintética"


@pytest.mark.parametrize("scenario, status, failure", [
    ("success", "completed", None),
    ("grasp_failed", "completed", None),
    ("wrong_piece", "stopped", "wrong_piece"),
    ("missing_piece", "stopped", "missing_piece"),
])
def test_required_replays_are_available_and_labelled(client, scenario, status, failure):
    view = finished(client, start(client, scenario, "replay"))
    assert (view["mode"], view["status"], view["failure_class"]) == ("replay", status, failure)
    assert view["synthetic"] is True and view["replay_of"]


def test_stop_reason_is_shown_for_a_stopped_run(client):
    view = finished(client, start(client, "wrong_piece"))
    assert view["status"] == "stopped" and "pieza distinta" in view["stop_reason"]


def test_view_links_initial_reference_and_observed_images_per_step(client):
    view = finished(client, start(client, "wrong_piece"))
    place = next(s for s in view["steps"] if s["action"] == "place" and s["piece_id"] == "B")
    for key in ("initial", "reference", "observed"):
        assert client.get(f"/api/runs/{view['run_id']}/files/{place['images'][key]}").status_code == 200
    assert place["outcome"] == "fail"


def test_view_keeps_the_four_state_layers_apart(client):
    view = finished(client, start(client, "wrong_piece"))
    assert set(view["state"]) == {"requested", "commanded", "observed", "uncertainty"}
    assert view["state"]["requested"]["B"] == "center" and view["state"]["observed"]["center"] == "C"


def test_files_cannot_escape_the_run_folder(client, tmp_path):
    (tmp_path / "secreto.txt").write_text("x", encoding="utf-8")
    run_id = start(client)
    finished(client, run_id)
    for path in ("../../secreto.txt", "..%2F..%2Fsecreto.txt", "manifest.json"):
        assert client.get(f"/api/runs/{run_id}/files/{path}").status_code == 404


def test_requests_for_another_host_are_refused(client):
    assert client.get("/api/status", headers={"host": "evil.example"}).status_code == 400


def test_software_stop_reaches_a_running_engine(tmp_path, monkeypatch):
    from premonition.web import create_app

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    client = TestClient(create_app(root=tmp_path, pace_s=0.3), base_url="http://127.0.0.1")
    run_id = start(client)
    stop = client.post(f"/api/runs/{run_id}/stop").json()
    assert "no es un paro de emergencia" in stop["detail"].lower()
    view = finished(client, run_id)
    assert (view["status"], view["failure_class"]) == ("stopped", "operator_stop")


def test_evaluation_endpoint_reports_a2_and_a3_on_synthetic_data(client):
    report = client.post("/api/evaluation").json()
    assert report["provenance"]["real_runs"] == 0 and report["warning"]
    assert report["methods"]["A2"]["trials"] == report["methods"]["A3"]["trials"] > 0


def test_camera_failure_is_shown_as_a_failure(client, monkeypatch):
    from premonition import web

    def unreachable(*args, **kwargs):
        return subprocess.CompletedProcess(args, 255, b"", b"ssh: connect timed out")

    monkeypatch.setattr(web.jetson_link.subprocess, "run", unreachable, raising=True)
    response = client.post("/api/camera/capture")
    assert response.status_code == 502 and "timed out" in response.json()["detail"]


def test_no_module_of_the_pc_application_imports_i2c():
    for path in (ROOT / "premonition").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import smbus" not in text and "smbus2" not in text, path


def test_no_module_starts_the_servo_programs():
    for path in (ROOT / "premonition").glob("*.py"):
        if path.name not in ("first_motion.py", "arm_session.py"):
            text = path.read_text(encoding="utf-8")
            assert "mindarm_arm" not in text and "servo_test" not in text, path


def test_cli_demo_labels_the_result_as_simulated(tmp_path, capsys):
    from premonition.cli import main

    assert main(["demo", "--scenario", "missing_piece", "--root", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "SIMULACIÓN" in output and "missing_piece" in output


def test_cli_gaps_lists_missing_physical_data(capsys, monkeypatch, real_cell):
    from premonition import cli
    from premonition.cli import main
    monkeypatch.setattr(cli, "load_cell", lambda p: real_cell.model_copy(update={"stop_procedure_confirmed": False}))
    assert main(["gaps"]) == 0
    assert "parada física" in capsys.readouterr().out


def test_cli_meta_smoke_without_key_is_pending_not_success(monkeypatch, capsys):
    from premonition.cli import main

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    assert main(["meta-smoke"]) == 2
    assert "MODEL_API_KEY" in capsys.readouterr().out


def test_cli_analyze_arm_reports_a_meta_failure(tmp_path, monkeypatch, capsys):
    from premonition import arm_vision
    from premonition.cli import main
    from premonition.meta import MetaError

    def fail(client, root, trial):
        raise MetaError(500, "boom")
    monkeypatch.setenv("MODEL_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(arm_vision, "analyze_trial", fail)
    assert main(["analyze-arm", "--trial", "t1", "--root", str(tmp_path)]) == 1
    assert "Vision analysis failed" in capsys.readouterr().out


def test_cli_evaluate_writes_a_report(tmp_path, capsys):
    from premonition.cli import main

    assert main(["evaluate", "--root", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "fixtures" / "synthetic" / "evaluation.json").read_text(encoding="utf-8"))
    assert report["provenance"]["real_runs"] == 0
    assert "no son evidencia" in capsys.readouterr().out


def meta_app(tmp_path, monkeypatch, handler):
    import httpx

    from premonition import web
    from premonition.meta import Budget, MetaClient

    def fake_client(on_usage=None):
        http = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.meta.ai/v1")
        return MetaClient("clave-falsa", Budget(max_calls=20, max_usd=1.0), http=http, on_usage=on_usage)

    monkeypatch.setattr(web, "client_from_env", fake_client)
    return TestClient(web.create_app(root=tmp_path, pace_s=0.0), base_url="http://127.0.0.1")


def meta_handler(sim_cell, image_status=200):
    import base64

    import httpx

    from premonition.planner import build_kit_plan
    from premonition.sim import SCENARIOS, SimWorld

    plan = build_kit_plan({"A": "left", "B": "center", "C": "right"}, sim_cell).model_dump_json()
    jpeg = base64.b64encode(SimWorld(SCENARIOS["success"], sim_cell).render(seq=1)).decode()

    def handler(request):
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"content": plan}}],
                                             "usage": {"prompt_tokens": 100, "completion_tokens": 50}})
        if image_status != 200:
            return httpx.Response(image_status, json={"error": {"message": "sobrecarga"}})
        return httpx.Response(200, json={"data": [{"b64_json": jpeg}], "usage": {}})

    return handler


def test_meta_run_names_the_real_models_and_records_all_usage(tmp_path, monkeypatch, sim_cell):
    client = meta_app(tmp_path, monkeypatch, meta_handler(sim_cell))
    assert client.get("/api/status").json()["meta"]["configured"] is True
    view = finished(client, start(client, use_meta=True))
    assert (view["planner_source"], view["reference_source"]) == ("muse-spark-1.3", "muse-image-1.0")
    models = [entry["model"] for entry in view["api_usage"]]
    assert models[0] == "muse-spark-1.3" and models.count("muse-image-1.0") == 6


def test_meta_image_failure_is_visible_and_never_replaced_by_a_fixture(tmp_path, monkeypatch, sim_cell):
    client = meta_app(tmp_path, monkeypatch, meta_handler(sim_cell, image_status=503))
    view = finished(client, start(client, use_meta=True))
    assert "503" in view["reference_failures"][0]
    assert view["reference_source"] == "muse-image-1.0"
    assert all("reference" not in step["images"] for step in view["steps"])


def test_meta_planner_failure_is_reported_and_starts_nothing(tmp_path, monkeypatch):
    import httpx

    client = meta_app(tmp_path, monkeypatch, lambda request: httpx.Response(401, json={"error": {"message": "no"}}))
    response = client.post("/api/runs", json={"scenario": "success", "mode": "simulation",
                                              "request_text": REQUEST_TEXT, "use_meta": True})
    assert response.status_code == 502 and "401" in response.json()["detail"]
    assert client.get("/api/runs").json() == []


def test_autonomy_latest_is_empty_before_any_run(tmp_path):
    from premonition import web

    client = TestClient(web.create_app(root=tmp_path, pace_s=0.0), base_url="http://127.0.0.1")
    assert client.get("/api/autonomy/latest").json() == {"run": None}
    assert client.get("/api/autonomy/latest.jpg").status_code == 404
    assert client.get("/autonomy").status_code == 200


def test_autonomy_latest_serves_last_run_and_image(tmp_path):
    from premonition import web

    folder = tmp_path / "real/autonomy"
    folder.mkdir(parents=True)
    (folder / "20261103-010000.json").write_text('{"run_id": "20261103-010000", "phase": "done"}', encoding="utf-8")
    (folder / "20261103-020000.json").write_text('{"run_id": "20261103-020000", "phase": "place"}', encoding="utf-8")
    (folder / "commands.jsonl").write_text("{}\n", encoding="utf-8")
    (folder / "latest.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    client = TestClient(web.create_app(root=tmp_path, pace_s=0.0), base_url="http://127.0.0.1")
    assert client.get("/api/autonomy/latest").json() == {"run": {"run_id": "20261103-020000", "phase": "place"}}
    image = client.get("/api/autonomy/latest.jpg")
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"


POSES = [{"base": 1500, "shoulder": 1600, "elbow": 2290}, {"base": 1520, "shoulder": 1610, "elbow": 2200},
         {"base": 1540, "shoulder": 1620, "elbow": 2100}]


def command_line(t, id, pulses, ok=True, duration=0.5):
    reply = {"id": id, "ok": ok, "stopped": False, "positions": dict(pulses), "error": None}
    return json.dumps({"t": t, "targets": {}, "duration": duration, "reply": reply})


def write_commands(tmp_path, *lines):
    folder = tmp_path / "real/autonomy"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "commands.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def bench_client(tmp_path):
    from premonition import web

    return TestClient(web.create_app(root=tmp_path, pace_s=0.0), base_url="http://127.0.0.1")


def test_arm_model_is_nominal_before_any_fit(tmp_path):
    body = bench_client(tmp_path).get("/api/arm/model").json()
    assert body["nominal"] is True and body["units"] == "mm"
    assert body["atlas"] == [] and body["table"] is None and body["fit"] is None
    assert body["workspace"]["scanned"] == []
    assert 0 < len(body["workspace"]["limits"]) <= 2000


def test_arm_model_atlas_and_fit_summary(tmp_path):
    from premonition import arm_model

    folder = tmp_path / "real/calibration"
    folder.mkdir(parents=True)
    (folder / "capabilities.json").write_text(json.dumps(
        {"atlas": [{"pulses": p, "tip": {}, "t": 1.0} for p in POSES]}), encoding="utf-8")
    (folder / "arm_model_fit_report.json").write_text('{"summary": {"rms": 3.2}, "other": 1}', encoding="utf-8")
    body = bench_client(tmp_path).get("/api/arm/model").json()
    assert body["atlas"] == [arm_model.chain(arm_model.NOMINAL, p)[3] for p in POSES]
    assert body["fit"] == {"rms": 3.2}
    assert 0 < len(body["workspace"]["scanned"]) <= 2000


def test_commands_split_into_sessions_and_keyframes_carry_the_chain(tmp_path):
    from premonition import arm_model

    write_commands(tmp_path, command_line(100.0, 1, POSES[0]), command_line(101.0, 2, POSES[1], duration=1.5),
                   command_line(102.0, 1, POSES[2]), command_line(300.0, 2, POSES[0]))
    client = bench_client(tmp_path)
    sessions = client.get("/api/arm/sessions").json()
    assert [(s["index"], s["start"], s["end"], s["moves"]) for s in sessions] == [
        (0, 100.0, 101.0, 2), (1, 102.0, 102.0, 1), (2, 300.0, 300.0, 1)]
    keyframes = client.get("/api/arm/replay/0").json()["keyframes"]
    assert [k["t"] for k in keyframes] == [100.0, 101.0] and keyframes[1]["duration"] == 1.5
    assert keyframes[1]["pulses"] == POSES[1]
    assert keyframes[1]["chain"] == arm_model.chain(arm_model.NOMINAL, POSES[1])


def test_live_pose_skips_truncated_and_refused_commands(tmp_path):
    client = bench_client(tmp_path)
    assert client.get("/api/arm/live").json() == {"pulses": None}
    write_commands(tmp_path, command_line(time.time() - 5, 1, POSES[0]), command_line(time.time(), 2, POSES[1], ok=False),
                   '{"t": 1, "reply": null}', '{"t": 2, "reply": {"id": 3, "ok": tr')
    live = client.get("/api/arm/live").json()
    assert live["pulses"] == POSES[0] and len(live["chain"]) == 4 and 4 < live["age_s"] < 60


def test_replay_of_an_unknown_session_is_404(tmp_path):
    write_commands(tmp_path, command_line(100.0, 1, POSES[0]))
    client = bench_client(tmp_path)
    assert client.get("/api/arm/replay/1").status_code == 404
    assert client.get("/api/arm/replay/0").status_code == 200


def test_sessions_list_the_runs_that_started_inside_them(tmp_path):
    folder = tmp_path / "real/autonomy"
    folder.mkdir(parents=True)
    inside = "2026-11-03T07:40:00+00:00"
    t = datetime.fromisoformat(inside).timestamp()
    (folder / "r-in.json").write_text(json.dumps({"run_id": "r-in", "started_at": inside, "tries": []}), encoding="utf-8")
    (folder / "r-out.json").write_text(json.dumps({"run_id": "r-out", "started_at": "2026-11-03T09:00:00+00:00"}),
                                       encoding="utf-8")
    (folder / "r-early.json").write_text(json.dumps({"run_id": "r-early", "started_at": "2026-11-03T07:39:30+00:00"}),
                                         encoding="utf-8")
    (folder / "r-before.json").write_text(json.dumps({"run_id": "r-before", "started_at": "2026-11-03T07:37:00+00:00"}),
                                          encoding="utf-8")
    write_commands(tmp_path, command_line(t - 10, 1, POSES[0]), command_line(t + 10, 2, POSES[1]))
    client = bench_client(tmp_path)
    assert client.get("/api/arm/sessions").json()[0]["runs"] == ["r-early", "r-in"]
    assert client.get("/api/autonomy/runs/r-in").json()["tries"] == []
    assert client.get("/api/autonomy/runs/missing").status_code == 404
    assert client.get("/api/autonomy/runs/..%2Fcommands").status_code == 404


def test_arm_page_loads_no_external_scripts_or_styles(tmp_path):
    client = bench_client(tmp_path)
    page = client.get("/autonomy").text
    assert not re.search(r'<script[^>]*src="http', page) and not re.search(r'<link[^>]*href="http', page)
    assert '<script src="/static/arm3d.js"></script>' in page
    script = client.get("/static/arm3d.js")
    assert script.status_code == 200 and "http" not in script.text
    images = re.findall(r'<img[^>]*src="([^"]*)"', page)
    assert images and all(src.startswith("http://127.0.0.1:8767/") for src in images)
    assert all(url.startswith("http://127.0.0.1:8767/") for url in re.findall(r"https?://[^\s\"'`]+", page))


def test_learning_ranks_arms_from_non_legacy_attempts(tmp_path):
    from dataclasses import asdict

    from premonition.grasp_policy import ARMS

    client = bench_client(tmp_path)
    prior = client.get("/api/arm/learning").json()["arms"]
    assert len(prior) == 20 and all(a["attempts"] == a["successes"] == 0 for a in prior)
    assert [a["params"] for a in prior] == [asdict(arm) for depth in (90, 60) for arm in ARMS if arm.depth_px == depth]
    assert not (tmp_path / "real").exists()

    def tried(arm, lifted):
        return {"t": 5.0, "skill": "grasp", "params": asdict(arm), "lifted": lifted,
                "class": "lifted" if lifted else "pushed", "legacy": False}

    memory = {"grasp_offset_usb_x": 0, "successes": 0,
              "failures": [{"t": 1.0, "reason": "not_lifted", "offset": 0}, {"t": 2.0, "reason": "not_lifted", "offset": 0}],
              "attempts": [dict(tried(ARMS[0], False), legacy=True), tried(ARMS[0], True), tried(ARMS[2], False),
                           {"t": 6.0, "skill": "place", "class": "placed", "legacy": False}, tried(ARMS[0], True),
                           tried(ARMS[2], False)]}
    path = tmp_path / "real/calibration/skill_memory.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(memory), encoding="utf-8")
    arms = client.get("/api/arm/learning").json()["arms"]
    assert len(arms) == 20 and sum(a["attempts"] for a in arms) == 4
    assert arms[0] == {"params": asdict(ARMS[0]), "rate": 0.75, "attempts": 2, "successes": 2, "alpha": 3, "beta": 1}
    assert arms[-1] == {"params": asdict(ARMS[2]), "rate": 0.4, "attempts": 2, "successes": 0, "alpha": 2, "beta": 3}
    assert [a["rate"] for a in arms] == sorted((a["rate"] for a in arms), reverse=True)
    assert json.loads(path.read_text(encoding="utf-8")) == memory


def test_workspace_and_teach_pages_link_to_autonomy(tmp_path):
    client = bench_client(tmp_path)
    for page in ("/", "/calibration"):
        assert 'href="/autonomy"' in client.get(page).text


def test_workspace_says_the_real_arm_runs_from_the_terminal(tmp_path):
    client = bench_client(tmp_path)
    assert "terminal" in client.get("/api/status").json()["motion"]["detail"]
    page, script = client.get("/").text, client.get("/static/app.js").text
    assert "Runs from the terminal" in page and "Disabled" not in page + script
    assert "gaps-box" not in page and "Hardware setup" not in script


GRASP = {"offset_usb_x": -30, "depth_px": 60, "max_steps": 4, "grip_open_us": 1850, "elbow_min_us": 2050}


def grasp_try(t, **extra):
    return {"t": t, "skill": "grasp", "params": GRASP, "lifted": False, "class": "too_shallow", "descent_stop": "cap",
            "tip_end": [600.0, 700.0], "rise_px": 1.0, "muse_offset": None, "legacy": False, "seconds": 30.0, **extra}


def test_last_attempts_are_the_newest_ten_real_grasps_first(tmp_path, monkeypatch):
    from premonition import web

    monkeypatch.setattr(web, "INSPECTION", tmp_path / "inspection")
    client = bench_client(tmp_path)
    assert client.get("/api/arm/attempts").json() == {"attempts": []}
    failed_reach = grasp_try(130.0, **{"class": "reach_failed", "reach": "diverging", "seconds": 8.4})
    del failed_reach["descent_stop"]
    memory = {"grasp_offset_usb_x": 0, "successes": 0, "failures": [{"t": 200.0, "reason": "not_lifted", "offset": 0}],
              "attempts": [grasp_try(50.0, legacy=True), *(grasp_try(100.0 + i) for i in range(11)),
                           {"t": 120.0, "skill": "place", "class": "placed", "legacy": False}, failed_reach]}
    path = tmp_path / "real/calibration/skill_memory.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(memory), encoding="utf-8")
    attempts = client.get("/api/arm/attempts").json()["attempts"]
    assert [a["t"] for a in attempts] == [130.0, *(110.0 - i for i in range(9))]
    assert attempts[0] == {"t": 130.0, "class": "reach_failed", "params": GRASP, "seconds": 8.4,
                           "reach": "diverging", "descent_stop": None, "photos": []}
    assert attempts[1] == {"t": 110.0, "class": "too_shallow", "params": GRASP, "seconds": 30.0,
                           "reach": None, "descent_stop": "cap", "photos": []}
    assert json.loads(path.read_text(encoding="utf-8")) == memory


def photo_folder(tmp_path, monkeypatch, *names):
    from premonition import web

    folder = tmp_path / "inspection"
    folder.mkdir()
    for name in names:
        (folder / name).write_bytes(b"\xff\xd8\xff\xd9")
    monkeypatch.setattr(web, "INSPECTION", folder)


LIMA = timezone(timedelta(hours=-5))


def test_last_attempts_link_each_try_to_its_own_photos(tmp_path, monkeypatch):
    photo_folder(tmp_path, monkeypatch, "grasp-004554-try2-descent-20261103.jpg", "grasp-004554-try2-lift-20261103.jpg",
                 "grasp-004554-try3-lift-20261103.jpg", "grasp-235959-try1-lift-20261103.jpg", "grasp-004554-notes.jpg")
    run = datetime(2026, 11, 4, 0, 45, 54, tzinfo=LIMA).timestamp()
    memory = {"attempts": [grasp_try(datetime(2026, 11, 4, 0, 0, 30, tzinfo=LIMA).timestamp()),
                           grasp_try(datetime(2026, 11, 4, 0, 30, 0, tzinfo=LIMA).timestamp()),
                           grasp_try(run + 11.6, **{"class": "reach_failed", "reach": "no_progress"}),
                           grasp_try(run + 39.2), grasp_try(run + 49.9)]}
    path = tmp_path / "real/calibration/skill_memory.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(memory), encoding="utf-8")
    attempts = bench_client(tmp_path).get("/api/arm/attempts").json()["attempts"]
    assert [a["photos"] for a in attempts] == [
        ["grasp-004554-try3-lift-20261103.jpg"],
        ["grasp-004554-try2-descent-20261103.jpg", "grasp-004554-try2-lift-20261103.jpg"],
        [], [], ["grasp-235959-try1-lift-20261103.jpg"]]


def test_attempt_photos_use_lima_time_on_a_machine_in_another_zone(tmp_path, monkeypatch):
    from premonition import web

    class UtcMachine(datetime):
        @classmethod
        def fromtimestamp(cls, t, tz=None):
            return datetime.fromtimestamp(t, tz or timezone.utc)
    monkeypatch.setattr(web, "datetime", UtcMachine)
    photo_folder(tmp_path, monkeypatch, "grasp-004554-try1-lift-20261103.jpg")
    path = tmp_path / "real/calibration/skill_memory.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"attempts": [grasp_try(datetime(2026, 11, 4, 0, 46, 30, tzinfo=LIMA).timestamp())]}),
                    encoding="utf-8")
    attempts = bench_client(tmp_path).get("/api/arm/attempts").json()["attempts"]
    assert attempts[0]["photos"] == ["grasp-004554-try1-lift-20261103.jpg"]


def test_attempt_photos_are_served_only_by_their_exact_name(tmp_path, monkeypatch):
    photo_folder(tmp_path, monkeypatch, "grasp-004554-try2-lift-20261103.jpg", "notes.jpg")
    (tmp_path / "grasp-004554-try1-lift-20261103.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    client = bench_client(tmp_path)
    photo = client.get("/api/arm/photos/grasp-004554-try2-lift-20261103.jpg")
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/jpeg"
    for name in ("notes.jpg", "grasp-004554-try9-lift-20261103.jpg", "..%2Fgrasp-004554-try1-lift-20261103.jpg",
                 "..%5Cgrasp-004554-try1-lift-20261103.jpg", "grasp-004554-try2-lift-20261103.jpg%00.txt"):
        assert client.get(f"/api/arm/photos/{name}").status_code == 404
