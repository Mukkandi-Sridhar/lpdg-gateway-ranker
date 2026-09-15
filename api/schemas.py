"""Response shapes. FastAPI turns these into the schemas shown at /docs and /openapi.json."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    detail: str = Field(description="What went wrong, in words a caller can act on")


class RunError(BaseModel):
    error: str = Field(description="data_error, config_error or internal_error")
    detail: str = Field(description="What went wrong; the previous rankings are still served")


class RankedGateway(BaseModel):
    rank: int = Field(description="1 to 15, strongest evidence first")
    gateway_id: str = Field(description="12 uppercase hex characters", examples=["0A00000000FF"])
    score: float = Field(description="Risk points, 0 to 100 for the improved ranker")
    reason: str = Field(description="Plain-words reason for the operations manager, at most 300 characters")


class Rankings(BaseModel):
    week_start: str = Field(examples=["2026-02-02"])
    ranker: str = Field(examples=["improved"])
    generated_at: str = Field(description="When the run that built this ranking finished (UTC)")
    gateways: list[RankedGateway]


class GatewayExplanation(BaseModel):
    gateway_id: str
    week_start: str
    summary: str = Field(description="Rank, or how far the gateway is from the 15, or why it is not eligible")
    rank: int | None = Field(description="1 to 15, or null when not in the 15")
    score: float
    cutoff_score: float = Field(description="Score of the 15th pick that week")
    eligible: bool = Field(description="False when decommissioned, not installed yet, or already visited")
    reason: str
    components: dict[str, float] = Field(description="The numbers behind the score; keys depend on the ranker")
    ranker: str


class Weeks(BaseModel):
    weeks: list[str] = Field(description="Every week with a ranking, oldest first")
    scored_weeks: list[str] = Field(description="The weeks written to predictions.csv")
    latest_week: str


class RunSummary(BaseModel):
    status: str = Field(examples=["ok"])
    ranker: str
    weeks_ranked: int
    scored_weeks: list[str]
    latest_week: str
    rows: int = Field(description="Rows written to predictions.csv")
    duration_sec: float
    data_months: list[str] = Field(description="Telemetry months found in the data folder")
    warnings: list[str] = Field(description="Problems worth a look, e.g. a network-wide telemetry gap")


class HealthChecks(BaseModel):
    data_dir: bool
    telemetry_files: bool
    results: bool


class LastRun(BaseModel):
    finished_at: str
    ranker: str
    latest_week: str
    duration_sec: float
    warnings: list[str]


class Health(BaseModel):
    status: str = Field(description="ok or unhealthy")
    checks: HealthChecks
    run_in_progress: bool
    last_run_error: str | None = Field(description="Why the most recent POST /run failed, if it did")
    last_run: LastRun | None = None
    stale: bool | None = Field(None, description="True when telemetry months on disk differ from the last run's")
