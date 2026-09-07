from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class CatalogStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class QualityState(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_EVALUATED = "not_evaluated"


class RootInfo(BaseModel):
    id: str
    path: str
    available: bool


class EvidenceFile(BaseModel):
    path: str
    exists: bool
    role: str


class QualityMetric(BaseModel):
    key: str
    label: str
    state: QualityState
    value: str
    threshold: str | None = None
    category: str = "acquisition"
    evidence: list[EvidenceFile] = Field(default_factory=list)
    note: str | None = None
    measurement_class: str | None = None
    measurement_basis: str | None = None
    ground_truth_required: bool = False
    ground_truth_available: bool = False


class PipelineCapability(BaseModel):
    key: Literal["integrity", "ego", "retarget", "quality", "export"]
    enabled: bool
    reason: str


class CaptureSummary(BaseModel):
    capture_id: str
    semantic_id: str
    display_name: str
    task_description: str | None = None
    operator: str | None = None
    root_id: str
    status: CatalogStatus
    native_status: str
    created_at: str | None = None
    updated_at: str | None = None
    device: str | None = None
    fps: float | None = None
    frame_count: int | None = None
    source_format: str | None = None
    ego_available: bool = False
    robot_datasets: list[str] = Field(default_factory=list)
    indexed_bytes: int | None = None
    failure_reason: str | None = None
    quality: list[QualityMetric] = Field(default_factory=list)
    capabilities: list[PipelineCapability] = Field(default_factory=list)


class CaptureDetail(CaptureSummary):
    path: str
    stages: dict[str, Any] = Field(default_factory=dict)
    datasets: dict[str, Any] = Field(default_factory=dict)
    manifest_warnings: list[str] = Field(default_factory=list)


class CaptureMetadataUpdate(BaseModel):
    semantic_id: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    display_name: str = Field(min_length=1, max_length=120)
    task_description: str | None = Field(default=None, max_length=500)
    operator: str | None = Field(default=None, max_length=80)


class ScanResult(BaseModel):
    scanned_at: str
    roots: int
    captures: int
    warnings: list[str] = Field(default_factory=list)


class RunStage(BaseModel):
    key: str
    label: str
    status: Literal["pending", "running", "completed", "failed", "cancelled", "skipped"]
    progress: int = Field(ge=0, le=100)


class RunCreate(BaseModel):
    capture_id: str
    root_id: str
    pipeline: Literal["integrity", "ego", "retarget", "quality", "export", "full"] = "integrity"
    robot_target: Literal[
        "nero_inspire_rgb", "nero_inspire_rgbd", "nero_inspire_rgbd_anchored",
        "nero_gripper_rgb", "nero_gripper_rgbd",
    ] = "nero_inspire_rgbd"
    target_revision: str = Field(default="target_revision_v001", pattern=r"^[A-Za-z0-9_.-]+$")
    retarget_revision: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]+$")
    export_scope: Literal["ego", "robot", "all"] = "all"


class ProcessingRun(BaseModel):
    run_id: str
    capture_id: str
    root_id: str
    pipeline: str
    executor: Literal["local"] = "local"
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    progress: int = Field(ge=0, le=100)
    current_stage: str | None = None
    stages: list[RunStage] = Field(default_factory=list)
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    failure_reason: str | None = None
    logs: list[str] = Field(default_factory=list)
    robot_target: str | None = None
    target_revision: str | None = None
    retarget_revision: str | None = None
    export_scope: Literal["ego", "robot", "all"] = "all"
    artifacts: list[str] = Field(default_factory=list)
