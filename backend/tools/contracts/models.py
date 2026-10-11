from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

READ = "vibeshorts:read"
GENERATE = "vibeshorts:generate"
CANCEL = "vibeshorts:cancel"
SCOPES = {READ, GENERATE, CANCEL}
Id = str
JobState = Literal[
    "queued",
    "claimed",
    "submitting",
    "waiting_for_provider",
    "materializing",
    "succeeded",
    "failed",
    "submission_unknown",
    "cancel_requested",
    "cancelled",
]
RunState = Literal[
    "queued",
    "running",
    "waiting_for_jobs",
    "needs_approval",
    "needs_reconciliation",
    "succeeded",
    "failed",
    "cancelled",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Caller(Contract):
    uid: str
    auth_time: float
    projects: list[str] | None = None
    scopes: list[str] = Field(default_factory=lambda: sorted(SCOPES))
    grant_id: str | None = None


class ImageInput(Contract):
    prompt: str = Field(min_length=1, max_length=8000)
    aspect_ratio: Literal["9:16", "16:9"] = "9:16"
    reference_artifact_ids: list[str] = Field(default_factory=list, max_length=3)
    spend_cap_micros: int | None = Field(default=None, ge=0)


class ImageCommand(Contract):
    project_id: str
    idempotency_key: str = Field(min_length=1, max_length=200)
    input: ImageInput


class JobHandle(Contract):
    job_id: str
    run_id: str
    step_id: str
    status: JobState
    artifact_ids: list[str] = Field(default_factory=list)
    poll_after_seconds: int = 2


class PublicError(Contract):
    code: str
    message: str
    retryable: bool = False
    action: str | None = None
    job_id: str | None = None


class Budget(Contract):
    cap_micros: int = Field(ge=0)
    reserved_micros: int = Field(default=0, ge=0)
    settled_micros: int = Field(default=0, ge=0)
    currency: Literal["USD"] = "USD"


class Artifact(Contract):
    id: str
    project_id: str
    run_id: str | None = None
    job_id: str | None = None
    parent_id: str | None = None
    input_artifact_ids: list[str] = Field(default_factory=list)
    type: Literal["image", "video", "audio", "composition", "storyboard", "font", "render"] = "image"
    title: str
    storage_uri: str
    content_sha256: str
    brand_version: str | None = None
    provider: dict[str, Any] | None = None
    media: dict[str, Any]
    created_at: float


class BrandInput(Contract):
    colors: dict[str, str] = Field(default_factory=dict)
    fonts: dict[str, str] = Field(default_factory=dict)
    logo: str | None = None
    reference_frames: list[str] = Field(default_factory=list, max_length=3)
    do: list[str] = Field(default_factory=list)
    dont: list[str] = Field(default_factory=list)
    caption: dict[str, list[str]] = Field(default_factory=dict)


class BrandRevision(BrandInput):
    id: str
    version: int
    project_id: str
    created_at: float


class JobResult(JobHandle):
    costs: dict[str, Any]
    error: PublicError | None = None
    created_at: float
    updated_at: float


class RunResult(Contract):
    run_id: str
    project_id: str
    status: RunState
    version: int
    brand_version: str | None
    active_steps: list[dict[str, Any]]
    pending_approval_id: str | None = None
    approval: dict[str, Any] | None = None
    workflow: dict[str, Any] | None = None


class DataResult(Contract):
    data: dict[str, Any]


class AssetPage(Contract):
    assets: list[dict[str, Any]]
    next_cursor: str | None = None


class Mutation(Contract):
    idempotency_key: str = Field(min_length=1, max_length=200)


class ProjectCreate(Mutation):
    name: str = Field(min_length=1, max_length=120)
    spend_cap_micros: int | None = Field(default=None, ge=0)


class BrandUpdate(Mutation):
    expected_version: int = Field(ge=0)
    brand: BrandInput


class UploadCreate(Mutation):
    title: str = Field(min_length=1, max_length=120)
    mime_type: Literal[
        "image/png", "image/jpeg", "video/mp4", "audio/wav", "audio/mpeg", "font/woff2", "font/ttf"
    ]
    size_bytes: int = Field(gt=0, le=200_000_000)


class UploadComplete(Mutation):
    upload_id: str
