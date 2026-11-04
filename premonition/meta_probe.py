"""Local record of a bounded API test. Stores no API key or request content."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .meta import IMAGE_MODEL, SAM_MODEL, SPARK_MODEL

MODELS = {SPARK_MODEL, IMAGE_MODEL, SAM_MODEL}


def save_probe(root: Path, api_key: str, events: list[dict], passed: bool) -> dict:
    fields = {"model", "path", "status", "latency_ms", "usd", "input_tokens", "output_tokens"}
    safe_events = [{k: v for k, v in event.items() if k in fields} for event in events]
    report = {"checked_at": datetime.now(timezone.utc).isoformat(),
              "key_sha256": hashlib.sha256(api_key.encode()).hexdigest(),
              "passed": passed, "synthetic_input": True, "actuators_used": False,
              "estimated_usd": sum(event.get("usd", 0) for event in safe_events), "events": safe_events}
    folder = Path(root) / "real" / "meta_smoke"
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / "access.tmp"
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temporary.replace(folder / "access.json")
    return report


def verified_access(root: Path, api_key: str | None) -> bool:
    if not api_key:
        return False
    path = Path(root) / "real" / "meta_smoke" / "access.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        matches = report["key_sha256"] == hashlib.sha256(api_key.encode()).hexdigest()
        checked = {event["model"] for event in report["events"] if event.get("status") == 200}
        return matches and report.get("passed") is True and MODELS <= checked
    except (OSError, ValueError, KeyError, TypeError):
        return False
