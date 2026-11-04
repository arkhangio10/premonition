"""Operator-marked image regions. These are not robot coordinates or motion routes."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .scene_vision import load_capture


class ImageRegion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=10)
    h: int = Field(ge=10)


def validate_regions(source: ImageRegion, destination: ImageRegion, width: int, height: int):
    for region in (source, destination):
        if region.x + region.w > width or region.y + region.h > height:
            raise ValueError("Keep both areas inside the photo.")
    overlap = (max(source.x, destination.x) < min(source.x+source.w, destination.x+destination.w)
               and max(source.y, destination.y) < min(source.y+source.h, destination.y+destination.h))
    if overlap:
        raise ValueError("Pick-up and destination areas must not overlap.")


def save_workspace(root: Path, capture: dict, source: ImageRegion, destination: ImageRegion) -> dict:
    _, _, frame = load_capture(root, capture)
    validate_regions(source, destination, frame["width"], frame["height"])
    report = {"id": uuid.uuid4().hex, "created_at": datetime.now(timezone.utc).isoformat(),
              "capture": frame, "source": source.model_dump(), "destination": destination.model_dump(),
              "operator_marked": True, "motion_calibrated": False,
              "note": "Image regions only. Pick, place and connecting trajectories must still be taught."}
    folder = Path(root) / "real/calibration/workspaces"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (report["id"]+".json")
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    temporary.replace(path)
    return report


def latest_workspace(root: Path) -> dict | None:
    folder = Path(root) / "real/calibration/workspaces"
    if not folder.exists():
        return None
    for path in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            _, _, frame = load_capture(root, report["capture"])
            validate_regions(ImageRegion.model_validate(report["source"]),
                             ImageRegion.model_validate(report["destination"]), frame["width"], frame["height"])
            if report["operator_marked"] is True and report["motion_calibrated"] is False:
                return report
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None


def latest_proposal(root: Path) -> dict | None:
    """Return a prepared proposal for review; never treat it as operator approval."""
    folder = Path(root) / "real/calibration"
    for path in sorted(folder.glob("workspace_proposal_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            _, _, frame = load_capture(root, report["capture"])
            validate_regions(ImageRegion.model_validate(report["source"]),
                             ImageRegion.model_validate(report["destination"]), frame["width"], frame["height"])
            if report["operator_confirmed"] is False and report["motion_calibrated"] is False:
                return report
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None
