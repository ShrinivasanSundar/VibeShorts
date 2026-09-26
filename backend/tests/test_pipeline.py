"""Unit and Integration Tests for VibeShorts Pipeline Components."""

import subprocess
from pathlib import Path
import pytest

from src.core.config import settings
from src.models.schemas import (
    BoundingBox,
    WordTimestamp,
    Shot,
    RollType,
    FootageIndex,
    CreativeBrief,
    EditPlan,
    EditPlanEntry,
    ReviewPatch,
    PatchType
)
from src.services.refiner.snap_refiner import TrimRefiner
from src.services.editor.ass_generator import ASSCaptionGenerator
from src.services.editor.ffmpeg_builder import FFmpegEditor
from src.services.reviewer.patch_router import PatchRouter


def test_bounding_box_center():
    box = BoundingBox(ymin=0.0, xmin=0.2, ymax=1.0, xmax=0.8)
    assert box.center_x == 0.5
    assert box.center_y == 0.5


def test_trim_refiner_snaps_to_word_boundaries():
    refiner = TrimRefiner()
    words = [
        WordTimestamp(word="Hello", start=1.05, end=1.45),
        WordTimestamp(word="world", start=1.52, end=1.95),
        WordTimestamp(word="VibeShorts", start=2.20, end=2.85),
    ]
    shot = Shot(
        shot_id="shot_001",
        source_file_uri="test.mp4",
        sha256_hash="dummy_hash",
        start_time=0.0,
        end_time=5.0,
        duration=5.0,
        roll_type=RollType.A_ROLL,
        transcript="Hello world VibeShorts",
        words=words,
        has_speech=True
    )
    index = FootageIndex(project_id="test_proj", shots=[shot], total_raw_duration=5.0)

    # Initial rough cut from 1.1s to 2.5s (in middle of "Hello" and between "world" and "VibeShorts")
    rough_entry = EditPlanEntry(
        cut_index=1,
        shot_id="shot_001",
        source_file_uri="test.mp4",
        in_point_sec=1.1,
        out_point_sec=2.5
    )
    plan = EditPlan(plan_id="plan_test", project_id="test_proj", cuts=[rough_entry], total_target_duration=1.4)

    refined = refiner.refine_plan(plan, index)
    cut = refined.cuts[0]

    # In-point should snap before "Hello" (start 1.05 -> ~0.97s)
    assert cut.in_point_sec < 1.05
    # Out-point should snap cleanly after "world" or "VibeShorts"
    assert cut.out_point_sec > 1.95


def test_ass_caption_generator(tmp_path: Path):
    generator = ASSCaptionGenerator()
    words = [
        WordTimestamp(word="AI", start=0.1, end=0.4),
        WordTimestamp(word="VIDEO", start=0.45, end=0.9),
    ]
    shot = Shot(
        shot_id="s1",
        source_file_uri="dummy.mp4",
        sha256_hash="h1",
        start_time=0.0,
        end_time=3.0,
        duration=3.0,
        words=words
    )
    index = FootageIndex(project_id="p1", shots=[shot], total_raw_duration=3.0)
    entry = EditPlanEntry(cut_index=1, shot_id="s1", source_file_uri="dummy.mp4", in_point_sec=0.0, out_point_sec=2.0)
    plan = EditPlan(plan_id="p1", project_id="p1", cuts=[entry], total_target_duration=2.0)

    ass_file = tmp_path / "test.ass"
    generator.generate_ass_file(plan, index, ass_file)

    assert ass_file.exists()
    content = ass_file.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content
    assert "AI VIDEO" in content


def test_patch_router_bifurcation():
    router = PatchRouter()

    # Story patch routes to Director
    story_patch = ReviewPatch(
        patch_type=PatchType.TIGHTEN_HOOK,
        target_cut_index=1,
        target_entity="director",
        rationale="Hook too slow",
        suggested_action="Shorten cut 1"
    )
    is_terminal, next_actor, patches = router.route_patches([story_patch], current_revision=1)
    assert not is_terminal
    assert next_actor == "director"

    # Editor patch routes to Editor
    editor_patch = ReviewPatch(
        patch_type=PatchType.FIX_CAPTION_DRIFT,
        target_cut_index=1,
        target_entity="editor",
        rationale="Subtitle offset",
        suggested_action="Shift 0.1s"
    )
    is_terminal, next_actor, patches = router.route_patches([editor_patch], current_revision=1)
    assert not is_terminal
    assert next_actor == "editor"

    # Max retries forces completion
    is_terminal, next_actor, _ = router.route_patches([story_patch], current_revision=settings.MAX_REVIEW_RETRIES)
    assert is_terminal
    assert next_actor == "complete"
