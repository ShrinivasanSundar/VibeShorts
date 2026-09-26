"""Integration test for FFmpeg 9:16 re-framing and ASS subtitle rendering."""

import subprocess
from pathlib import Path
import pytest
from src.core.config import settings
from src.models.schemas import (
    EditPlan,
    EditPlanEntry,
    FootageIndex,
    Shot,
    WordTimestamp,
    BoundingBox,
    RollType
)
from src.services.editor.ffmpeg_builder import FFmpegEditor


def create_synthetic_test_clip(output_path: Path, duration: int = 4) -> Path:
    """Generates a synthetic 1920x1080 video with a moving sine wave audio tone."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        settings.FFMPEG_PATH,
        "-y",
        "-f", "lavfi",
        "-i", f"testsrc=size=1920x1080:rate=30",
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={duration}",
        "-t", str(duration),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(output_path)
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return output_path


def test_ffmpeg_end_to_end_render(tmp_path: Path):
    # 1. Create synthetic source media
    source_clip = tmp_path / "raw_synthetic.mp4"
    create_synthetic_test_clip(source_clip, duration=4)
    assert source_clip.exists()

    # 2. Build Shot metadata and FootageIndex
    words = [
        WordTimestamp(word="VIBE", start=0.2, end=0.8),
        WordTimestamp(word="SHORTS", start=0.85, end=1.5),
        WordTimestamp(word="AUTONOMOUS", start=1.6, end=2.4),
    ]
    shot = Shot(
        shot_id="synthetic_shot_01",
        source_file_uri=str(source_clip.resolve()),
        sha256_hash="synthetic_hash",
        start_time=0.0,
        end_time=4.0,
        duration=4.0,
        roll_type=RollType.A_ROLL,
        transcript="VibeShorts Autonomous",
        words=words,
        has_speech=True,
        primary_focus_box=BoundingBox(ymin=0.0, xmin=0.25, ymax=1.0, xmax=0.75)
    )
    index = FootageIndex(
        project_id="test_render_proj",
        shots=[shot],
        total_raw_duration=4.0
    )

    # 3. Create EditPlan with two cuts
    cut1 = EditPlanEntry(
        cut_index=1,
        shot_id="synthetic_shot_01",
        source_file_uri=str(source_clip.resolve()),
        in_point_sec=0.0,
        out_point_sec=1.5,
        crop_9_16=BoundingBox(ymin=0.0, xmin=0.21875, ymax=1.0, xmax=0.78125)
    )
    cut2 = EditPlanEntry(
        cut_index=2,
        shot_id="synthetic_shot_01",
        source_file_uri=str(source_clip.resolve()),
        in_point_sec=1.5,
        out_point_sec=3.0,
        crop_9_16=BoundingBox(ymin=0.0, xmin=0.21875, ymax=1.0, xmax=0.78125)
    )
    plan = EditPlan(
        plan_id="plan_synth_01",
        project_id="test_render_proj",
        total_target_duration=3.0,
        cuts=[cut1, cut2]
    )

    # 4. Render using FFmpegEditor
    editor = FFmpegEditor()
    output_mp4 = tmp_path / "rendered_final.mp4"
    editor.render_edit_plan(plan, index, output_mp4)

    assert output_mp4.exists()
    assert output_mp4.stat().st_size > 1000

    # 5. Verify video resolution with ffprobe: must be 1080x1920 (9:16 vertical)
    probe_cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        str(output_mp4)
    ]
    res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    w, h = res.stdout.strip().split("x")
    assert int(w) == 1080
    assert int(h) == 1920
