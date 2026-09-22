"""Pipeline runner — orchestrates the full create workflow."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from vibeshorts.agents.director import DirectorAgent
from vibeshorts.agents.editor import EditorAgent
from vibeshorts.agents.reviewer import ReviewerAgent
from vibeshorts.agents.trim_refiner import TrimRefinerAgent
from vibeshorts.config import VibeShortsConfig
from vibeshorts.integrations.vertex.lyria import LyriaClient
from vibeshorts.integrations.vertex.veo import VeoClient
from vibeshorts.models.schemas import CreativeBrief, FootageIndex
from vibeshorts.pipeline.preprocess import preprocess_footage

console = Console()


class PipelineRunner:
    def __init__(self, config: VibeShortsConfig, project_dir: Path):
        self.config = config
        self.project_dir = project_dir
        self.work_dir = project_dir / ".vibeshorts" / "work"
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def _load_pipeline_steps(self, pipeline_path: Path | None) -> list[dict]:
        path = pipeline_path or Path(self.config.default_pipeline)
        if not path.exists():
            return [
                {"agent": "director"},
                {"agent": "trim_refiner"},
                {"agent": "editor"},
                {"agent": "reviewer", "retry_if": {"metric": "overall", "threshold": 0.65, "max_retries": 2}},
            ]
        data = yaml.safe_load(path.read_text()) or {}
        return data.get("steps", [])

    def run(
        self,
        footage_dir: Path,
        brief: CreativeBrief,
        output: Path,
        pipeline_path: Path | None = None,
        style_path: Path | None = None,
        skip_preprocess: bool = False,
        engine: str = "ffmpeg",
        generate_music: bool = False,
        generate_broll: bool = False,
    ) -> Path:
        index_path = self.project_dir / "footage_index.json"
        feedback: str | None = None
        attempt = 0
        max_retries = self.config.max_retries

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            if not skip_preprocess or not index_path.exists():
                task = progress.add_task("Preprocessing footage...", total=None)
                index = preprocess_footage(footage_dir)
                index_path.write_text(index.model_dump_json(indent=2))
                progress.remove_task(task)
            else:
                index = FootageIndex.model_validate_json(index_path.read_text())

            steps = self._load_pipeline_steps(pipeline_path)
            director = DirectorAgent(self.config)
            trim_refiner = TrimRefinerAgent(self.config, self.work_dir / "probes")
            editor = EditorAgent(self.config, self.work_dir / "segments")
            reviewer = ReviewerAgent(self.config, self.project_dir)

            music_path = None
            if generate_music and brief.tone:
                task = progress.add_task("Generating background music (Lyria)...", total=None)
                try:
                    lyria = LyriaClient(self.config)
                    music_path = lyria.generate_music(
                        f"Background music for {brief.product}, tone: {brief.tone}",
                        duration_seconds=brief.duration_seconds,
                        output_path=self.work_dir / "music.wav",
                    )
                except Exception as exc:
                    console.print(f"[yellow]Lyria skipped: {exc}[/]")
                progress.remove_task(task)

            if generate_broll:
                task = progress.add_task("Generating B-roll (Veo)...", total=None)
                try:
                    veo = VeoClient(self.config)
                    bucket = self.config.gcp.genmedia_bucket or "gs://vibeshorts-output"
                    veo.generate_broll(
                        prompt=f"B-roll for {brief.product}, {brief.tone}",
                        output_gcs_uri=f"{bucket}/broll/",
                    )
                except Exception as exc:
                    console.print(f"[yellow]Veo skipped: {exc}[/]")
                progress.remove_task(task)

            while attempt <= max_retries:
                attempt_label = f" (v{attempt})" if attempt else ""
                plan = None

                for step in steps:
                    agent_name = step.get("agent", "")
                    if agent_name == "director":
                        progress.add_task(f"Director planning{attempt_label}...", total=None)
                        plan = director.create_plan(brief, index, style_path, feedback)
                        (self.work_dir / f"edit_plan{attempt_label}.json").write_text(
                            plan.model_dump_json(indent=2)
                        )
                    elif agent_name == "trim_refiner" and plan:
                        progress.add_task("Refining trim points...", total=None)
                        plan = trim_refiner.refine(plan, index)
                    elif agent_name == "editor" and plan:
                        progress.add_task(f"Rendering ({engine})...", total=None)
                        timeline = editor.plan_to_timeline(plan, index)
                        timeline.save(self.project_dir / "timeline.json")
                        attempt_output = output if attempt == 0 else output.with_stem(f"{output.stem}_v{attempt}")
                        if engine == "hyperframes":
                            editor.render_hyperframes(self.project_dir, attempt_output)
                        else:
                            editor.render_ffmpeg(plan, index, attempt_output, music_path)
                        output = attempt_output
                    elif agent_name == "reviewer":
                        retry_cfg = step.get("retry_if", {})
                        threshold = retry_cfg.get("threshold", self.config.review_threshold)
                        progress.add_task("Reviewing output...", total=None)
                        score = reviewer.review_sync(brief, output, threshold)
                        (self.work_dir / f"review{attempt_label}.json").write_text(
                            score.model_dump_json(indent=2)
                        )
                        console.print(
                            f"[bold]Review score:[/] {score.overall:.2f} "
                            f"(adherence={score.adherence:.2f}, pacing={score.pacing:.2f})"
                        )
                        if score.passed:
                            console.print("[green]Review passed![/]")
                            return output
                        if attempt >= retry_cfg.get("max_retries", max_retries):
                            console.print("[yellow]Max retries reached; returning best attempt.[/]")
                            return output
                        feedback = score.critique
                        attempt += 1
                        break

                if plan and "reviewer" not in {s.get("agent") for s in steps}:
                    return output

        return output
