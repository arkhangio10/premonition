"""Modelos de datos: plan, celda, contrato, observación y veredicto."""
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class Mode(str, Enum):
    SIMULATION = "simulation"
    REPLAY = "replay"


class InspectScene(Strict):
    step_id: str
    action: Literal["inspect_scene"]
    scope: Literal["initial", "final"]


class Pick(Strict):
    step_id: str
    action: Literal["pick"]
    piece_id: str
    source_id: str


class Place(Strict):
    step_id: str
    action: Literal["place"]
    piece_id: str
    destination_id: str


class VerifyStep(Strict):
    step_id: str
    action: Literal["verify_step"]
    target_step_id: str


class StopStep(Strict):
    step_id: str
    action: Literal["stop"]
    reason: str = Field(max_length=200)


Step = Annotated[InspectScene | Pick | Place | VerifyStep | StopStep, Field(discriminator="action")]


class Plan(Strict):
    steps: list[Step]


class Appearance(Strict):
    hue: float
    hue_tol: float
    sat_min: int
    val_min: int


class Region(Strict):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(gt=0)
    h: int = Field(gt=0)


class Location(Strict):
    id: str
    kind: Literal["source", "destination"]
    label: str
    region: Region | None


class PieceSpec(Strict):
    id: str
    label: str
    source_id: str
    appearance: Appearance | None
    sam_phrase: str | None


class Waypoint(Strict):
    name: str
    targets_us: dict[str, int] | None
    duration_s: float | None = Field(gt=0, le=10)


class Route(Strict):
    waypoints: list[Waypoint]
    validated_by_operator: bool


class Perception(Strict):
    background_bgr: tuple[int, int, int]
    foreground_delta: float
    occupied_min: float
    empty_max: float
    occluder_val_max: int
    occlusion_max: float
    identity_min: float
    identity_margin: float
    position_tol_norm: float
    brightness_min: float
    brightness_max: float
    saturated_max: float
    sharpness_min: float
    reference_similarity_min: float


class Limits(Strict):
    max_plan_steps: int = Field(gt=0, le=256)
    max_attempts: int = Field(gt=0, le=10)
    max_reobserve: int = Field(ge=0, le=10)
    settle_s: float = Field(ge=0, le=30)


class Cell(Strict):
    schema_version: int
    cell_id: str
    synthetic: bool
    note: str
    stop_procedure_confirmed: bool
    joints: list[str]
    envelope_us: dict[str, tuple[int, int]]
    max_speed_us_s: float = Field(gt=0, le=1000)
    pieces: list[PieceSpec]
    locations: list[Location]
    observe_pose: Waypoint | None
    routes: dict[str, Route]
    perception: Perception | None
    limits: Limits

    def piece(self, piece_id: str) -> PieceSpec | None:
        return next((p for p in self.pieces if p.id == piece_id), None)

    def location(self, location_id: str) -> Location | None:
        return next((l for l in self.locations if l.id == location_id), None)


class Predicate(Strict):
    kind: Literal["piece_present", "region_empty"]
    region: str
    piece: str | None = None


class Contract(Strict):
    """Resultado físico exigido, fijado antes de actuar. La referencia nunca lo modifica."""
    contract_id: str
    run_id: str
    step_id: str
    attempt: int
    plan_sha256: str
    action: str
    role: Literal["inspect", "final", "pre", "post"]
    piece_id: str | None
    predicates: list[Predicate]
    initial_frame_sha256: str | None
    reference_sha256: str | None
    reference_source: str | None
    thresholds_sha256: str


class CaptureRequest(Strict):
    run_id: str
    step_id: str
    attempt: int
    phase: str
    command_id: str | None
    token: str


class Frame(Strict):
    frame_id: str
    run_id: str
    step_id: str
    attempt: int
    phase: str
    command_id: str | None
    token: str
    source: Literal["synthetic", "replay", "jetson"]
    jpeg: bytes
    sha256: str


class RegionMeasure(Strict):
    region: str
    occupancy: float
    occlusion: float
    best_piece: str | None
    identity_score: float
    identity_margin: float
    offset_norm: float | None


class Verdict(Strict):
    outcome: Literal["pass", "fail", "unknown"]
    reasons: list[str]
    failure_class: str | None = None


class MotionCommand(Strict):
    command_id: str
    run_id: str
    step_id: str
    attempt: int
    action: str
    piece_id: str
    location_id: str


class MotionResult(Strict):
    command_id: str
    status: Literal["completed", "stopped", "rejected", "unknown"]
    detail: str
