from typing import Any, Literal

from pydantic import Field, model_validator

from tools.contracts.models import Contract, ImageInput, Mutation


class VideoInput(ImageInput):
    first_frame_artifact_id: str
    source_duration_seconds: Literal[4, 6, 8] = 6
    resolution: Literal["720p", "1080p"] = "720p"
    generate_audio: bool = True

    @model_validator(mode="after")
    def supported(self):
        if self.reference_artifact_ids:
            raise ValueError("Asset reference mode is not interchangeable with the first-frame workflow")
        if self.resolution == "1080p" and self.source_duration_seconds != 8:
            raise ValueError("1080p requires an 8-second source")
        return self


class MusicInput(Contract):
    prompt: str = Field(min_length=1, max_length=4000)
    instrumental: Literal[True] = True
    duration_seconds: float = Field(default=30, ge=1, le=32.8)
    reference_artifact_ids: list[str] = Field(default_factory=list, max_length=0)
    spend_cap_micros: int | None = Field(default=None, ge=0)


class PrepareInput(Contract):
    artifact_id: str
    in_seconds: float = Field(default=0, ge=0)
    out_seconds: float = Field(gt=0, le=120)
    aspect_ratio: Literal["9:16", "16:9"] = "9:16"
    mute: bool = True
    reference_artifact_ids: list[str] = Field(default_factory=list, max_length=0)
    spend_cap_micros: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def timing(self):
        if self.out_seconds <= self.in_seconds:
            raise ValueError("Out point must be after in point")
        return self


class FrameInput(Contract):
    artifact_id: str
    frame_index: int = Field(ge=0)
    reference_artifact_ids: list[str] = Field(default_factory=list, max_length=0)
    spend_cap_micros: int | None = Field(default=None, ge=0)


class StoryAsset(Contract):
    """A reusable reference image generated once before any scene, so every scene shares it."""

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    kind: Literal["subject", "character", "location", "style"]
    description: str = Field(min_length=1, max_length=2000)
    reference_artifact_ids: list[str] = Field(default_factory=list, max_length=3)


class Scene(Contract):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    objective: str = Field(min_length=1, max_length=500)
    exact_copy: list[str] = Field(default_factory=list, max_length=3)
    editorial_duration_seconds: float = Field(gt=0, le=8)
    visual_prompt: str = Field(min_length=1, max_length=4000)
    reference_artifact_ids: list[str] = Field(default_factory=list, max_length=3)
    asset_ids: list[str] = Field(default_factory=list, max_length=3)
    continuity_from_scene_id: str | None = None


class CreativePreferences(Contract):
    vibe: Literal["cinematic", "cartoon", "collage", "3d"] | None = None
    motion: Literal["real_time", "slow_motion"] = "real_time"


class Storyboard(Contract):
    creative_preferences: CreativePreferences | None = None
    schema_version: Literal[1] = 1
    project_id: str
    brand_version: str | None = None
    skill_version: str = "product_launch@1.0"
    duration_seconds: float = Field(default=15, ge=6, le=30)
    aspect_ratio: Literal["9:16", "16:9"] = "9:16"
    fps: Literal[24] = 24
    assets: list[StoryAsset] = Field(default_factory=list, max_length=3)
    scenes: list[Scene] = Field(min_length=3, max_length=5)
    music: MusicInput

    @model_validator(mode="after")
    def plan(self):
        ids = [s.id for s in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("Scene ids must be unique")
        asset_ids = [a.id for a in self.assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("Asset ids must be unique")
        if any(not set(s.asset_ids) <= set(asset_ids) for s in self.scenes):
            raise ValueError("Scenes may only use assets defined in the storyboard")
        seen = set()
        for scene in self.scenes:
            if scene.continuity_from_scene_id and scene.continuity_from_scene_id not in seen:
                raise ValueError("Continuity must reference an earlier scene; cycles are forbidden")
            if any(len(copy) > 120 for copy in scene.exact_copy):
                raise ValueError("Overlay copy is limited to 120 characters per line")
            seen.add(scene.id)
        if abs(sum(s.editorial_duration_seconds for s in self.scenes) - self.duration_seconds) > 0.001:
            raise ValueError("Scene durations must sum to the editorial duration")
        return self


class BriefInput(Contract):
    brief: str = Field(min_length=3, max_length=6000)
    duration_seconds: float = Field(default=15, ge=6, le=30)
    aspect_ratio: Literal["9:16", "16:9"] = "9:16"
    policy: Literal["product_launch", "explainer", "social_ad"] = "product_launch"
    locale: str = Field(default="en", max_length=20)
    revision_of_run_id: str | None = None
    expected_head: str | None = None
    scene_overrides: dict[str, str] = Field(default_factory=dict, max_length=5)
    workflow_mode: Literal["bulk", "guided"] = "bulk"

    @model_validator(mode="after")
    def revision(self):
        if self.scene_overrides and (not self.revision_of_run_id or not self.expected_head):
            raise ValueError("Scene revisions require the original run and expected composition head")
        if any(not 3 <= len(v) <= 4000 for v in self.scene_overrides.values()):
            raise ValueError("Scene visual prompts must be between 3 and 4000 characters")
        return self

    reference_artifact_ids: list[str] = Field(default_factory=list, max_length=3)
    spend_cap_micros: int | None = Field(default=None, ge=0)


class Clip(Contract):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    artifact_id: str | None = None
    kind: Literal["video", "image", "text", "audio"]
    track: int = Field(ge=0, le=10)
    start: float = Field(ge=0, le=120)
    duration: float = Field(gt=0, le=120)
    source_in: float = Field(default=0, ge=0)
    text: str = Field(default="", max_length=240)
    volume: float = Field(default=0, ge=0, le=1)
    fade_in: float = Field(default=0, ge=0, le=5)
    fade_out: float = Field(default=0, ge=0, le=5)
    hidden: bool = False


class Composition(Contract):
    schema_version: Literal[1] = 1
    title: str = Field(default="Untitled composition", max_length=120)
    aspect_ratio: Literal["9:16", "16:9"] = "9:16"
    duration_seconds: float = Field(default=15, ge=1, le=120)
    fps: Literal[24] = 24
    fonts: dict[str, str] = Field(default_factory=dict)
    background: str = Field(default="#101014", pattern=r"^#[0-9a-fA-F]{6}$")
    foreground: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    accent: str = Field(default="#bf96f6", pattern=r"^#[0-9a-fA-F]{6}$")
    clips: list[Clip] = Field(default_factory=list, max_length=80)
    expected_head: str | None = None
    reference_artifact_ids: list[str] = Field(default_factory=list, max_length=0)
    spend_cap_micros: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def timeline(self):
        if len({c.id for c in self.clips}) != len(self.clips):
            raise ValueError("Clip ids must be unique")
        for clip in self.clips:
            if clip.start + clip.duration > self.duration_seconds + 0.001:
                raise ValueError("Clip extends beyond the composition")
            if clip.kind != "text" and not clip.artifact_id:
                raise ValueError("Media clips need an artifact")
            if clip.fade_in + clip.fade_out > clip.duration:
                raise ValueError("Fades cannot exceed clip duration")
        return self


class RenderInput(Contract):
    composition_artifact_id: str
    quality: Literal["draft", "final"] = "draft"
    reference_artifact_ids: list[str] = Field(default_factory=list, max_length=0)
    spend_cap_micros: int | None = Field(default=None, ge=0)


class EditInput(Contract):
    expected_head: str
    instruction: str = Field(min_length=1, max_length=2000)
    reference_artifact_ids: list[str] = Field(default_factory=list, max_length=0)
    spend_cap_micros: int | None = Field(default=None, ge=0)


class ConversationInput(Contract):
    instruction: str = Field(min_length=1, max_length=6000)
    context: dict[str, Any] = Field(default_factory=dict)
    reference_artifact_ids: list[str] = Field(default_factory=list, max_length=3)
    spend_cap_micros: int | None = Field(default=None, ge=0)


class DirectorTurn(Contract):
    text: str = Field(min_length=1, max_length=4000)
    action: Literal["clarify", "storyboard", "generate_scene", "edit_composition", "status"]
    storyboard: Storyboard | None = None
    scene_id: str | None = None
    instruction: str | None = Field(default=None, max_length=2000)
    storyboard_only: bool = False

    @model_validator(mode="after")
    def action_payload(self):
        if self.action == "storyboard" and self.storyboard is None:
            raise ValueError("A storyboard action requires a complete typed storyboard")
        if self.action == "generate_scene" and not self.scene_id:
            raise ValueError("A scene action requires an existing scene id")
        if self.action == "edit_composition" and not self.instruction:
            raise ValueError("An edit action requires an instruction")
        return self


class ConversationCreate(Mutation):
    composition_artifact_id: str | None = None

    @model_validator(mode="after")
    def source(self):
        if self.run_id and self.composition_artifact_id:
            raise ValueError("Choose a workflow or a composition, not both")
        return self

    title: str = Field(default="New video", min_length=1, max_length=120)
    run_id: str | None = None
    workflow_mode: Literal["bulk", "guided"] = "guided"


class ConversationMessage(Mutation):
    workflow_mode: Literal["bulk", "guided"] | None = None
    creative_preferences: CreativePreferences | None = None
    policy: Literal["product_launch", "explainer", "social_ad"] = "product_launch"
    text: str = Field(min_length=1, max_length=6000)
    duration_seconds: float = Field(default=15, ge=6, le=30)
    aspect_ratio: Literal["9:16", "16:9"] = "9:16"
    locale: str = Field(default="en", max_length=20)
    reference_artifact_ids: list[str] = Field(default_factory=list, max_length=3)
    spend_cap_micros: int | None = Field(default=None, ge=0)


class ConversationAction(Mutation):
    action: Literal["approve", "continue", "revise", "retry", "cancel", "remove_scene"]
    job_id: str | None = None
    scene_id: str | None = Field(default=None, min_length=1, max_length=100)
    approval_id: str | None = None
    target_artifact_id: str | None = None
    instruction: str | None = Field(default=None, min_length=1, max_length=2000)


class StudioCommand(Mutation):
    project_id: str
    conversation_id: str | None = None
    input: (
        VideoInput
        | MusicInput
        | PrepareInput
        | FrameInput
        | BriefInput
        | Composition
        | RenderInput
        | EditInput
        | ConversationInput
    )


class ApprovalDecision(Mutation):
    target_artifact_id: str
    approved: bool


class MemberUpdate(Mutation):
    uid: str
    role: Literal["editor", "viewer"] | None


class EditBrief(Mutation):
    expected_head: str
    instruction: str = Field(min_length=1, max_length=2000)


INPUTS = {
    "video": VideoInput,
    "music": MusicInput,
    "prepare": PrepareInput,
    "frame": FrameInput,
    "storyboard": BriefInput,
    "composition": Composition,
    "render": RenderInput,
    "edit": EditInput,
    "director_turn": ConversationInput,
}
