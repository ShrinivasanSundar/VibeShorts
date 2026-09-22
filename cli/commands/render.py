"""vibeshorts render — export timeline to video."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from vibeshorts.config import load_config
from vibeshorts.tools.hyperframes import render_hyperframes

console = Console()


def register(app: typer.Typer) -> None:
    @app.command("render")
    def render(
        project_dir: Path = typer.Option(Path("."), "--project", "-p"),
        output: Path = typer.Option(Path("renders/export.mp4"), "--output", "-o"),
        engine: str = typer.Option("hyperframes", "--engine", help="hyperframes or ffmpeg"),
        quality: str = typer.Option("high", "--quality"),
        config_path: Path = typer.Option(None, "--config", "-c"),
    ) -> None:
        """Render the current timeline.json to a final video."""
        config = load_config(config_path)
        project_dir = project_dir.resolve()
        output = project_dir / output

        if engine == "hyperframes":
            render_hyperframes(
                project_dir / "composition",
                output,
                bin_prefix=config.integrations.hyperframes_bin,
                quality=quality,
            )
        else:
            console.print("[yellow]FFmpeg render from timeline.json — use `vibeshorts create` for full pipeline[/]")
            timeline_path = project_dir / "timeline.json"
            if not timeline_path.exists():
                raise typer.Exit(1)
            console.print(f"Timeline found at {timeline_path}. Re-run create to render via FFmpeg.")

        console.print(f"[green]Rendered:[/] {output}")
