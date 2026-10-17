"""Gemini-compatible output schemas; validate final output with the strict contracts."""

from pydantic import Field, model_validator

from tools.contracts.studio import Clip, Composition, DirectorTurn, MusicInput, Scene, Storyboard


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

    @model_validator(mode="before")
    @classmethod
    def fit_durations(cls, data):
        # The model often misses the exact sum; rescale so the strict contract can accept it.
        try:
            scenes = data["scenes"]
            target = float(data.get("duration_seconds", 15))
            durations = [float(s["editorial_duration_seconds"]) for s in scenes]
        except (TypeError, KeyError, ValueError):
            return data
        total = sum(durations)
        if total <= 0 or abs(total - target) <= 0.001:
            return data
        fitted = [round(d * target / total, 2) for d in durations[:-1]]
        fitted.append(round(target - sum(fitted), 3))
        return {**data, "scenes": [{**s, "editorial_duration_seconds": d} for s, d in zip(scenes, fitted)]}


class DirectorComposition(Composition):
    schema_version: int = Field(default=1, ge=1, le=1)
    fps: int = Field(default=24, ge=24, le=24)
    clips: list[DirectorClip] = Field(default_factory=list, max_length=80)


class DirectorConversation(DirectorTurn):
    storyboard: DirectorStoryboard | None = None
