"""Editor agent — deterministic FFmpeg/Hyperframes rendering."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from vibeshorts.config import VibeShortsConfig
from vibeshorts.models.schemas import EditPlan, FootageIndex
from vibeshorts.models.timeline import Timeline, TimelineItem, TimelineTrack
from vibeshorts.tools.captions import burn_captions
from vibeshorts.tools.ffmpeg import concat_clips, extract_clip
from vibeshorts.tools.hyperframes import render_hyperframes

console = Console()


class EditorAgent:
    def __init__(self, config: VibeShortsConfig, work_dir: Path):
        self.config = config
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def plan_to_timeline(self, plan: EditPlan, index: FootageIndex) -> Timeline:
        timeline = Timeline.default_short_form()
        shot_map = {s.id: s for s in index.shots}
        position = 0.0

        aroll_track = next(t for t in timeline.tracks if t.id == "v1_aroll")
        for i, entry in enumerate(plan.entries):
            shot = shot_map.get(entry.shot_id)
            if not shot:
                continue
            duration = entry.end_trim - entry.start_trim
            item = TimelineItem(
                id=f"clip_{i}",
                source=shot.source_file,
                start_trim=entry.start_trim,
                end_trim=entry.end_trim,
                timeline_start=position,
                duration=duration,
                label=entry.text_overlay,
            )
            track = aroll_track if shot.roll_type == "a-roll" else next(
                t for t in timeline.tracks if t.id == "v2_broll"
            )
            track.items.append(item)
            position += duration

        timeline.duration = position
        return timeline

    def render_ffmpeg(
        self,
        plan: EditPlan,
        index: FootageIndex,
        output: Path,
        music_path: Path | None = None,
    ) -> Path:
        shot_map = {s.id: s for s in index.shots}
        clip_paths: list[Path] = []

        for i, entry in enumerate(plan.entries):
            shot = shot_map.get(entry.shot_id)
            if not shot:
                continue
            clip_out = self.work_dir / f"segment_{i:03d}.mp4"
            extract_clip(
                Path(shot.source_file),
                entry.start_trim,
                entry.end_trim,
                clip_out,
            )
            if shot.words:
                captioned = self.work_dir / f"segment_{i:03d}_cap.mp4"
                burn_captions(clip_out, shot.words, entry.start_trim, entry.end_trim, captioned)
                clip_paths.append(captioned)
            else:
                clip_paths.append(clip_out)

        output.parent.mkdir(parents=True, exist_ok=True)
        concat_clips(clip_paths, output, music_path=music_path)
        console.print(f"[green]Rendered:[/] {output}")
        return output

    def render_hyperframes(self, project_dir: Path, output: Path) -> Path:
        return render_hyperframes(
            project_dir / "composition",
            output,
            bin_prefix=self.config.integrations.hyperframes_bin,
        )
