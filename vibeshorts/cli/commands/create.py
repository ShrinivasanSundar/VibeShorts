"""vibeshorts create — autonomous short-form video generation."""

from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml
from rich.console import Console

from vibeshorts.config import load_config
from vibeshorts.models.schemas import CreativeBrief
from vibeshorts.pipeline.runner import PipelineRunner

console = Console()


def register(app: typer.Typer) -> None:
    @app.command("create")
    def create(
        footage_dir: Path = typer.Option(..., "--footage", "-f", help="Directory of raw video clips"),
        brief: str = typer.Option(..., "--brief", "-b", help="Creative brief JSON or YAML file path"),
        output: Path = typer.Option(Path("renders/final.mp4"), "--output", "-o"),
        project_dir: Path = typer.Option(Path("."), "--project", "-p"),
        config_path: Path = typer.Option(None, "--config", "-c"),
        pipeline: Path = typer.Option(None, "--pipeline"),
        style: Path = typer.Option(None, "--style"),
        engine: str = typer.Option("ffmpeg", "--engine", help="ffmpeg or hyperframes"),
        music: bool = typer.Option(False, "--music", help="Generate background music via Lyria"),
        broll: bool = typer.Option(False, "--broll", help="Generate B-roll via Veo"),
        skip_preprocess: bool = typer.Option(False, "--skip-preprocess"),
    ) -> None:
        """Turn raw footage + creative brief into a polished short-form video."""
        config = load_config(config_path)
        project_dir = project_dir.resolve()
        project_dir.mkdir(parents=True, exist_ok=True)

        brief_path = Path(brief)
        if brief_path.exists():
            raw = brief_path.read_text()
            brief_data = yaml.safe_load(raw) if brief_path.suffix in {".yaml", ".yml"} else json.loads(raw)
        else:
            brief_data = json.loads(brief)

        creative_brief = CreativeBrief.model_validate(brief_data)
        runner = PipelineRunner(config, project_dir)

        console.print("[bold cyan]VibeShorts Create[/]")
        console.print(f"  Footage: {footage_dir}")
        console.print(f"  Product: {creative_brief.product}")
        console.print(f"  Engine:  {engine}")

        result = runner.run(
            footage_dir=footage_dir,
            brief=creative_brief,
            output=project_dir / output,
            pipeline_path=pipeline,
            style_path=style,
            skip_preprocess=skip_preprocess,
            engine=engine,
            generate_music=music,
            generate_broll=broll,
        )
        console.print(f"\n[bold green]Done![/] Output: {result}")
