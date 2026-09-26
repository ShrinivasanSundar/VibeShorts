"""Core Pydantic data models for the VibeShorts autonomous video engine.

Adheres strictly to the architectural boundary:
- Ingest owns the clock (Speech-to-Text & deterministic VAD timestamps).
- Gemini owns semantic labeling, narrative design, and qualitative review.
- EditPlan carries the exact frame and audio mixing instructions for FFmpeg.
"""

from enum import Enum
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class RollType(str, Enum):
    A_ROLL = "a_roll"       # Primary talking head / speech driver
    B_ROLL = "b_roll"       # Cutaway / product shot / contextual visual
    GEN_VEO = "gen_veo"     # Generative B-roll (Vertex AI Veo)
    STILL = "still"         # Static image / graphic asset


class BoundingBox(BaseModel):
    """Normalized [0.0, 1.0] coordinates: (ymin, xmin, ymax, xmax)."""
    ymin: float = Field(ge=0.0, le=1.0, default=0.0)
    xmin: float = Field(ge=0.0, le=1.0, default=0.0)
    ymax: float = Field(ge=0.0, le=1.0, default=1.0)
    xmax: float = Field(ge=0.0, le=1.0, default=1.0)

    @property
    def center_x(self) -> float:
        return (self.xmin + self.xmax) / 2.0

    @property
    def center_y(self) -> float:
        return (self.ymin + self.ymax) / 2.0


class WordTimestamp(BaseModel):
    """Word-level timing emitted by Google Cloud Speech-to-Text."""
    word: str
    start: float = Field(description="Start time in seconds relative to the source clip/shot")
    end: float = Field(description="End time in seconds relative to the source clip/shot")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class Shot(BaseModel):
    """Represents a single atomic scene detected deterministically."""
    shot_id: str
    source_file_uri: str
    sha256_hash: str
    start_time: float = Field(description="Cut start in source media seconds")
    end_time: float = Field(description="Cut end in source media seconds")
    duration: float
    roll_type: RollType = RollType.B_ROLL
    semantic_description: str = Field(default="", description="Visual & narrative content labeled by Gemini")
    transcript: str = Field(default="")
    words: List[WordTimestamp] = Field(default_factory=list)
    average_loudness_lufs: float = -24.0
    primary_focus_box: Optional[BoundingBox] = None
    has_speech: bool = False


class FootageIndex(BaseModel):
    """Catalog of all indexed shots and assets available for a project."""
    project_id: str
    shots: List[Shot] = Field(default_factory=list)
    audio_tracks: List[str] = Field(default_factory=list, description="URIs for Lyria background music tracks")
    total_raw_duration: float = 0.0


class CreativeBrief(BaseModel):
    """User-supplied creative intent."""
    product_name: str
    target_audience: str
    tone: Literal["energetic", "dramatic", "educational", "humorous", "minimalist"] = "energetic"
    duration_seconds: int = Field(default=30, ge=5, le=60)
    key_value_props: List[str] = Field(default_factory=list)
    style_ref: Optional[str] = None
    call_to_action: str = Field(default="")
    user_prompt: Optional[str] = Field(default=None, description="Conversational edit request or direction")


class ChatMessage(BaseModel):
    """Conversational turn in the AI video editing chat."""
    id: str
    sender: Literal["user", "assistant", "system"]
    text: str
    timestamp: str
    action_type: Optional[str] = None
    payload: Optional[dict] = None


class MusicDuckingCue(BaseModel):
    """Audio envelope specifications for background music ducking under speech."""
    duck_start_sec: float
    duck_end_sec: float
    normal_volume_db: float = -14.0
    ducked_volume_db: float = -28.0


class EditPlanEntry(BaseModel):
    """Declarative specification for a single cut on the final timeline."""
    cut_index: int
    shot_id: str
    source_file_uri: str
    in_point_sec: float = Field(description="In-point snapped to nearest word or pause")
    out_point_sec: float = Field(description="Out-point snapped to nearest word or pause")
    crop_9_16: BoundingBox = Field(
        default_factory=lambda: BoundingBox(ymin=0.0, xmin=0.21875, ymax=1.0, xmax=0.78125),
        description="Normalized 9:16 crop window (center 56.25% for 16:9 source)"
    )
    caption_safe_box: BoundingBox = Field(
        default_factory=lambda: BoundingBox(ymin=0.15, xmin=0.10, ymax=0.78, xmax=0.90),
        description="Safe area clear of TikTok/Reels UI overlay chrome"
    )
    music_cues: Optional[MusicDuckingCue] = None
    text_overlay: Optional[str] = None

    @property
    def timeline_duration(self) -> float:
        return max(0.0, self.out_point_sec - self.in_point_sec)


class EditPlan(BaseModel):
    """Complete, deterministic rendering blueprint consumed by FFmpeg."""
    plan_id: str
    project_id: str
    revision: int = 1
    total_target_duration: float
    cuts: List[EditPlanEntry] = Field(default_factory=list)
    background_music_uri: Optional[str] = None


class PatchType(str, Enum):
    TIGHTEN_HOOK = "tighten_hook"
    SWAP_SHOT = "swap_shot"
    REFRAME_CROP = "reframe_crop"
    FIX_CAPTION_DRIFT = "fix_caption_drift"
    ADJUST_LOUDNESS = "adjust_loudness"


class ReviewPatch(BaseModel):
    """Remediation action emitted by the Reviewer Agent."""
    patch_type: PatchType
    target_cut_index: int
    target_entity: Literal["director", "editor"]
    rationale: str
    suggested_action: str
    applied: bool = False


class PipelineStage(str, Enum):
    IDLE = "idle"
    INGESTING = "ingesting"
    INDEXED = "indexed"
    DIRECTING = "directing"
    REFINING = "refining"
    RENDERING = "rendering"
    REVIEWING = "reviewing"
    PATCHING = "patching"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStatus(BaseModel):
    job_id: str
    project_id: str
    stage: PipelineStage
    progress_percentage: int = 0
    message: str = ""
    edit_plan: Optional[EditPlan] = None
    output_video_uri: Optional[str] = None
    error: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    edit_plan: Optional[EditPlan] = None
    brief: Optional[CreativeBrief] = None


class ChatResponse(BaseModel):
    message: str
    action: Optional[str] = None
    suggested_plan: Optional[EditPlan] = None
    suggested_brief: Optional[CreativeBrief] = None
    suggested_prompts: List[str] = Field(default_factory=list)

