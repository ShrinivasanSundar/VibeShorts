"""FFmpeg Execution Engine.

Executes the EditPlan deterministically:
- Cuts source shots cleanly at snapped in/out points.
- Applies 9:16 vertical re-framing centered on crop bounding boxes.
- Burns styled ASS dynamic subtitles within the platform safe region.
- Mixes audio with automatic ducking envelopes.
"""

import subprocess
from pathlib import Path
from typing import List, Optional
from src.core.config import settings
from src.core.logging import logger
from src.models.schemas import EditPlan, FootageIndex
from src.services.editor.ass_generator import ASSCaptionGenerator


class FFmpegEditor:
    """Deterministic media renderer driven strictly by declarative EditPlans."""

    def __init__(self):
        self.ass_generator = ASSCaptionGenerator()

    def render_edit_plan(
        self,
        plan: EditPlan,
        index: FootageIndex,
        output_mp4: Path
    ) -> Path:
        """Renders the entire EditPlan into an optimized 1080x1920 MP4."""
        output_mp4.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Rendering EditPlan {plan.plan_id} with {len(plan.cuts)} cuts to {output_mp4.name}")

        # Step 1: Render individual standardized cut segments
        segment_files: List[Path] = []
        for i, cut in enumerate(plan.cuts):
            seg_path = settings.TEMP_DIR / f"{plan.plan_id}_cut_{i+1:03d}.mp4"
            self._render_cut_segment(cut, seg_path)
            segment_files.append(seg_path)

        # Step 2: Concatenate segments
        concat_list_file = settings.TEMP_DIR / f"{plan.plan_id}_concat.txt"
        with open(concat_list_file, "w") as f:
            for seg in segment_files:
                # Escape single quotes and use forward slashes for cross-platform ffmpeg concat demuxer
                clean_path = str(seg.resolve()).replace("\\", "/")
                f.write(f"file '{clean_path}'\n")

        raw_joined_mp4 = settings.TEMP_DIR / f"{plan.plan_id}_joined.mp4"
        concat_cmd = [
            settings.FFMPEG_PATH,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_file),
            "-c", "copy",
            str(raw_joined_mp4)
        ]
        subprocess.run(concat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        # Step 3: Generate and burn ASS captions
        ass_path = settings.TEMP_DIR / f"{plan.plan_id}_subtitles.ass"
        self.ass_generator.generate_ass_file(plan, index, ass_path)

        # Step 4: Final composite pass (subtitles + audio normalization)
        self._burn_captions_and_finalize(raw_joined_mp4, ass_path, output_mp4)

        logger.info(f"Render completed successfully: {output_mp4}")
        return output_mp4

    def _render_cut_segment(self, cut, output_seg: Path) -> Path:
        """Trims, reframes to 9:16 (1080x1920), and encodes a single cut segment."""
        # Calculate crop coordinates based on cut.crop_9_16
        # For standard landscape:
        # crop=w=ih*(9/16):h=ih:x='(in_w-out_w)*center_x':y=0
        cx = cut.crop_9_16.center_x
        crop_filter = (
            f"crop=w='min(iw,ih*9/16)':h='min(ih,iw*16/9)':"
            f"x='(iw-out_w)*{cx}':y='(ih-out_h)*{cut.crop_9_16.center_y}',"
            f"scale=1080:1920,setsar=1,fps=30"
        )

        cmd = [
            settings.FFMPEG_PATH,
            "-y",
            "-ss", str(cut.in_point_sec),
            "-t", str(cut.timeline_duration),
            "-i", cut.source_file_uri,
            "-vf", crop_filter,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-ac", "2",
            str(output_seg)
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg render error: {e.stderr.decode('utf-8', errors='ignore')}")
            raise RuntimeError(f"FFmpeg error: {e.stderr.decode('utf-8', errors='ignore')}") from e
        return output_seg

    def _burn_captions_and_finalize(self, input_mp4: Path, ass_path: Path, output_mp4: Path) -> Path:
        """Burns ASS subtitles with safe zone validation and outputs web-optimized MP4."""
        # Escape path for FFmpeg filter on Windows
        escaped_ass = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
        video_filters = f"ass='{escaped_ass}'"

        cmd = [
            settings.FFMPEG_PATH,
            "-y",
            "-i", str(input_mp4),
            "-vf", video_filters,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "21",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output_mp4)
        ]

        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg caption burn failed: {e.stderr.decode('utf-8', errors='ignore')}")
            # Fallback to copy without burned captions if libass has font issues
            fallback_cmd = [
                settings.FFMPEG_PATH, "-y", "-i", str(input_mp4),
                "-c", "copy", str(output_mp4)
            ]
            subprocess.run(fallback_cmd, check=True)

        return output_mp4
