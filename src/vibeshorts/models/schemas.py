"""Pydantic schemas for the VibeShorts agent pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CreativeBrief(BaseModel):
    product: str
    audience: str
    tone: str
    duration_seconds: int = Field(default=30, ge=5, le=180)
    style_ref: str | None = None
    hook: str | None = None
    cta: str | None = None


class WordTimestamp(BaseModel):
    word: str
    start: float
    end: float


class Shot(BaseModel):
    id: str
    source_file: str
    start_time: float
    end_time: float
    transcript: str = ""
    words: list[WordTimestamp] = Field(default_factory=list)
    roll_type: Literal["a-roll", "b-roll", "unknown"] = "unknown"


class FootageIndex(BaseModel):
    shots: list[Shot] = Field(default_factory=list)
    total_duration: float = 0.0

    def search_text(self, query: str, limit: int = 10) -> list[Shot]:
        query_lower = query.lower()
        matches = [s for s in self.shots if query_lower in s.transcript.lower()]
        return matches[:limit]


class EditPlanEntry(BaseModel):
    shot_id: str
    start_trim: float
    end_trim: float
    position: int
    text_overlay: str | None = None
    transition: str | None = None


class EditPlan(BaseModel):
    entries: list[EditPlanEntry] = Field(default_factory=list)
    music_prompt: str | None = None
    broll_prompts: list[str] = Field(default_factory=list)
    notes: str | None = None


class ReviewScore(BaseModel):
    adherence: float = Field(ge=0.0, le=1.0)
    pacing: float = Field(ge=0.0, le=1.0)
    visual_quality: float = Field(ge=0.0, le=1.0)
    watchability: float = Field(ge=0.0, le=1.0)
    overall: float = Field(ge=0.0, le=1.0)
    critique: str = ""
    passed: bool = False

    def compute_overall(self) -> float:
        weights = (0.3, 0.25, 0.2, 0.25)
        self.overall = (
            self.adherence * weights[0]
            + self.pacing * weights[1]
            + self.visual_quality * weights[2]
            + self.watchability * weights[3]
        )
        return self.overall
