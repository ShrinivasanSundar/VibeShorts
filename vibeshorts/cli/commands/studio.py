"""vibeshorts studio — local web UI for timeline editing."""

from __future__ import annotations

from pathlib import Path

import typer
import uvicorn
from rich.console import Console

from vibeshorts.config import load_config
from vibeshorts.studio.server import create_app

console = Console()


def register(app: typer.Typer) -> None:
    @app.command("studio")
    def studio(
        project_dir: Path = typer.Option(Path("."), "--project", "-p"),
        host: str = typer.Option("127.0.0.1", "--host"),
        port: int = typer.Option(8787, "--port"),
        config_path: Path = typer.Option(None, "--config", "-c"),
    ) -> None:
        """Launch VibeShorts Studio — visual timeline + agent WebSocket."""
        config = load_config(config_path)
        project_dir = project_dir.resolve()
        fastapi_app = create_app(config, project_dir)

        console.print(f"[bold cyan]VibeShorts Studio[/] http://{host}:{port}")
        console.print("  WebSocket agent channel: /ws/agent")
        console.print("  Timeline API: /api/timeline")

        uvicorn.run(fastapi_app, host=host, port=port, log_level="info")
