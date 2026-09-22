"""vibeshorts chat — interactive showrunner agent session."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console

from vibeshorts.config import load_config
from vibeshorts.integrations.antigravity import ShowrunnerAgent

console = Console()


def register(app: typer.Typer) -> None:
    @app.command("chat")
    def chat(
        message: str = typer.Argument(..., help="Message to the showrunner agent"),
        project_dir: Path = typer.Option(Path("."), "--project", "-p"),
        attach: list[Path] = typer.Option(None, "--attach", "-a", help="Files to attach"),
        config_path: Path = typer.Option(None, "--config", "-c"),
    ) -> None:
        """Send a message to the Antigravity showrunner agent."""
        config = load_config(config_path)
        agent = ShowrunnerAgent(config, project_dir.resolve())

        async def _run() -> str:
            return await agent.chat(message, attach)

        response = asyncio.run(_run())
        console.print(response)
