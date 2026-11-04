"""Línea de comandos de Premonition Lab. Ningún comando inicia el servicio de servos."""
import argparse
import json
import os
import sys
from pathlib import Path

from .cell import hardware_gaps, load_cell
from .evaluation import evaluate
from .first_motion import CardRefused, build_card
from .jetson import (CameraError, JetsonError, capture_to_disk, check_agent_syntax, check_connection,
                     read_commanded_pulses, inspect_system)
from .meta import Budget, BudgetExceeded, MetaClient, MetaError, reference_prompt
from .models import Contract, Predicate
from .meta_probe import save_probe
from .planner import FixturePlanner
from .scenarios import fixture_path, record_fixture, run_scenario
from .sim import SCENARIOS, SimWorld
from .validator import plan_json_schema

PROJECT = Path(__file__).resolve().parent.parent
SIM_CELL = PROJECT / "config" / "sim_cell.json"
REAL_CELL = PROJECT / "config" / "cell.json"
DEFAULT_ROOT = PROJECT / "runs"
DEMO_REQUEST = "Coloca la pieza A a la izquierda, B en el centro y C a la derecha; comprueba que estén las tres."


def _host() -> str:
    return os.environ.get("PREMONITION_JETSON_HOST", "jetson-usb")


def cmd_serve(args) -> int:
    import uvicorn

    from .web import create_app

    print(f"Premonition Lab en http://127.0.0.1:{args.port}  (simulación; movimiento físico deshabilitado)")
    uvicorn.run(create_app(args.root), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def cmd_demo(args) -> int:
    cell = load_cell(SIM_CELL)
    plan = FixturePlanner().plan(DEMO_REQUEST, cell)
    result = run_scenario(SCENARIOS[args.scenario], cell, plan, args.root, request_text=DEMO_REQUEST)
    print("SIMULACIÓN: datos sintéticos, planificador y referencia fixture, sin actuadores.")
    print(f"escenario: {args.scenario}\nestado: {result.status}\nclase de fallo: {result.failure_class}")
    print(f"motivo: {result.stop_reason}\nevidencia: {result.store.path}")
    return 0


def cmd_evaluate(args) -> int:
    cell = load_cell(SIM_CELL)
    plan = FixturePlanner().plan(DEMO_REQUEST, cell)
    runs = [record_fixture(args.root, name, cell, plan) for name in SCENARIOS]
    report = evaluate([fixture_path(args.root, name) for name in SCENARIOS], cell)
    output = Path(args.root) / "fixtures" / "synthetic" / "evaluation.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n{len(runs)} ejecuciones sintéticas; informe en {output}")
    return 0


def cmd_gaps(args) -> int:
    for gap in hardware_gaps(load_cell(REAL_CELL)):
        print(f"- {gap}")
    return 0


def cmd_jetson_check(args) -> int:
    print(json.dumps(check_connection(_host()), ensure_ascii=False, indent=2))
    print(json.dumps({"agent_syntax": check_agent_syntax(_host())}, ensure_ascii=False, indent=2))
    return 0


def cmd_jetson_inspect(args) -> int:
    report = inspect_system(_host())
    report["controller"] = read_commanded_pulses(_host())
    output = Path(args.root) / "real" / "jetson_inspection.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nInspección de solo lectura guardada en {output}")
    return 0


def cmd_capture(args) -> int:
    try:
        print(json.dumps(capture_to_disk(_host(), args.root), ensure_ascii=False, indent=2))
    except CameraError as failure:
        print(f"La cámara falló: {failure}")
        return 1
    return 0


def cmd_first_motion_card(args) -> int:
    try:
        card = build_card(read_commanded_pulses(_host()), load_cell(REAL_CELL))
    except (JetsonError, CardRefused) as failure:
        print(f"Tarjeta no generada: {failure}")
        return 1
    output = Path(args.root) / "real" / "first_motion_card.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(card, ensure_ascii=False, indent=2))
    print(f"\nTarjeta guardada en {output}. Este comando no movió nada.")
    return 0


def cmd_meta_smoke(args) -> int:
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        print("Pendiente: define MODEL_API_KEY en el entorno o en .env. No se hizo ninguna llamada.")
        return 2
    probe_events = []
    def log_probe(event):
        probe_events.append(event)
        print(json.dumps(event))
    client = MetaClient(key, Budget(max_calls=3, max_usd=0.05), on_usage=log_probe)
    cell = load_cell(SIM_CELL)
    jpeg = SimWorld(SCENARIOS["success"], cell).render(seq=1)
    contract = Contract(contract_id="smoke", run_id="smoke", step_id="s1", attempt=1, plan_sha256="", action="place",
                        role="post", piece_id="A", predicates=[Predicate(kind="piece_present", region="left", piece="A")],
                        initial_frame_sha256=None, reference_sha256=None, reference_source=None, thresholds_sha256="")
    output = Path(args.root) / "real" / "meta_smoke"
    output.mkdir(parents=True, exist_ok=True)
    try:
        plan = client.chat_json("Devuelve un plan vacío.", "sin pasos", plan_json_schema(), "KitPlan")
        print(f"Muse Spark respondió {len(plan)} caracteres")
        (output / "reference.jpg").write_bytes(client.edit_image(jpeg, reference_prompt(contract, cell)))
        print(f"Muse Image guardó {output / 'reference.jpg'}")
        print(f"SAM encontró {len(client.segment(jpeg, 'red square'))} objetos")
    except MetaError as failure:
        save_probe(Path(args.root), key, probe_events, passed=False)
        print(f"Falló la API: {failure}")
        return 1
    save_probe(Path(args.root), key, probe_events, passed=True)
    return 0


def cmd_analyze_arm(args) -> int:
    from .arm_vision import analyze_trial

    key = os.environ.get("MODEL_API_KEY")
    if not key:
        print("Meta API key is not configured.")
        return 2
    events = []
    client = MetaClient(key, Budget(max_calls=1, max_usd=0.10), on_usage=events.append)
    try:
        report = analyze_trial(client, Path(args.root), args.trial)
    except (MetaError, ValueError, OSError, BudgetExceeded) as failure:
        print(f"Vision analysis failed: {str(failure).replace(key, '<key>')}")
        return 1
    finally:
        client.http.close()
    report["api_usage"] = events
    path = Path(args.root) / "real" / "calibration" / "vision" / f"{args.trial}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="premonition", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    def add(name, handler, **options):
        command = commands.add_parser(name)
        command.add_argument("--root", default=str(DEFAULT_ROOT))
        for option, config in options.items():
            command.add_argument(f"--{option}", **config)
        command.set_defaults(handler=handler)

    add("serve", cmd_serve, port={"type": int, "default": 8765})
    add("demo", cmd_demo, scenario={"choices": sorted(SCENARIOS), "default": "success"})
    add("evaluate", cmd_evaluate)
    add("gaps", cmd_gaps)
    add("jetson-check", cmd_jetson_check)
    add("jetson-inspect", cmd_jetson_inspect)
    add("capture", cmd_capture)
    add("first-motion-card", cmd_first_motion_card)
    add("meta-smoke", cmd_meta_smoke)
    add("analyze-arm", cmd_analyze_arm, trial={"required": True})
    args = parser.parse_args(argv)
    return args.handler(args)


def load_env_file(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and not line.lstrip().startswith("#") and value.strip():
            os.environ.setdefault(name.strip(), value.strip())


def entry():
    load_env_file(PROJECT / ".env")
    sys.exit(main())
