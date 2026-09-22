"""Trim Refiner — two-pass frame-accurate trim via probe clips."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console

from vibeshorts.config import VibeShortsConfig
from vibeshorts.integrations.vertex.gemini import GeminiClient
from vibeshorts.models.schemas import EditPlan, FootageIndex
from vibeshorts.tools.ffmpeg import extract_probe_clip

console = Console()
PROBE_WINDOW = 3.0
MAX_WORKERS = 6


class TrimRefinerAgent:
    def __init__(self, config: VibeShortsConfig, work_dir: Path):
        self.gemini = GeminiClient(config)
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def refine(self, plan: EditPlan, index: FootageIndex) -> EditPlan:
        shot_map = {s.id: s for s in index.shots}
        probes: list[tuple[int, str, Path, str]] = []

        for i, entry in enumerate(plan.entries):
            shot = shot_map.get(entry.shot_id)
            if not shot:
                continue
            source = Path(shot.source_file)
            start_probe = extract_probe_clip(
                source,
                max(shot.start_time, entry.start_trim - PROBE_WINDOW),
                entry.start_trim + PROBE_WINDOW,
                self.work_dir / f"probe_{i}_start.mp4",
            )
            end_probe = extract_probe_clip(
                source,
                max(shot.start_time, entry.end_trim - PROBE_WINDOW),
                entry.end_trim + PROBE_WINDOW,
                self.work_dir / f"probe_{i}_end.mp4",
            )
            probes.append((i, "start", start_probe, entry.shot_id))
            probes.append((i, "end", end_probe, entry.shot_id))

        refinements: dict[tuple[int, str], float] = {}

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {
                pool.submit(self.gemini.refine_trim_probe, probe_path, edge): (idx, edge)
                for idx, edge, probe_path, _ in probes
            }
            for future in as_completed(futures):
                idx, edge = futures[future]
                try:
                    result = future.result()
                    if result.get("confidence", 0) > 0.5:
                        refinements[(idx, edge)] = result.get("refined_time", 0.0)
                except Exception as exc:
                    console.print(f"[yellow]Trim probe failed for entry {idx} {edge}: {exc}[/]")

        for (idx, edge), delta in refinements.items():
            entry = plan.entries[idx]
            shot = shot_map.get(entry.shot_id)
            if not shot:
                continue
            if edge == "start":
                entry.start_trim = max(shot.start_time, entry.start_trim + delta - PROBE_WINDOW)
            else:
                entry.end_trim = min(shot.end_time, entry.end_trim + delta - PROBE_WINDOW)

        return plan
