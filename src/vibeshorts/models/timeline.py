"""Unified timeline.json representation for VibeShorts Studio."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class TimelineItem(BaseModel):
    id: str
    source: str
    start_trim: float = 0.0
    end_trim: float | None = None
    timeline_start: float = 0.0
    duration: float | None = None
    label: str | None = None
    metadata: dict = Field(default_factory=dict)


class TimelineTrack(BaseModel):
    id: str
    type: Literal["video", "audio", "overlay"]
    items: list[TimelineItem] = Field(default_factory=list)


class Timeline(BaseModel):
    duration: float = 0.0
    fps: int = 30
    aspect_ratio: str = "9:16"
    tracks: list[TimelineTrack] = Field(default_factory=list)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.model_dump(), indent=2))

    @classmethod
    def load(cls, path: Path) -> Timeline:
        return cls.model_validate_json(path.read_text())

    @classmethod
    def default_short_form(cls) -> Timeline:
        return cls(
            tracks=[
                TimelineTrack(id="v3_graphics", type="overlay", items=[]),
                TimelineTrack(id="v2_broll", type="video", items=[]),
                TimelineTrack(id="v1_aroll", type="video", items=[]),
                TimelineTrack(id="a1_voice", type="audio", items=[]),
                TimelineTrack(id="a2_music", type="audio", items=[]),
            ]
        )
