"""Gemini-compatible output schemas; validate final output with the strict contracts."""

from pydantic import Field

from tools.contracts.studio import Clip, Composition, MusicInput, Scene, Storyboard


class DirectorMusic(MusicInput):
    instrumental: bool = Field(default=True, description="Must be true: instrumental music only")


class DirectorScene(Scene):
    editorial_duration_seconds: float = Field(ge=0, le=8, description="Must be greater than zero")


class DirectorClip(Clip):
    duration: float = Field(ge=0, le=120, description="Must be greater than zero")


class DirectorStoryboard(Storyboard):
    schema_version: int = Field(default=1, ge=1, le=1)
    fps: int = Field(default=24, ge=24, le=24)
    music: DirectorMusic
    scenes: list[DirectorScene] = Field(min_length=3, max_length=5)


class DirectorComposition(Composition):
    schema_version: int = Field(default=1, ge=1, le=1)
    fps: int = Field(default=24, ge=24, le=24)
    clips: list[DirectorClip] = Field(default_factory=list, max_length=80)
