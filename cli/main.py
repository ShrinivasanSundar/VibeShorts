"""VibeShorts CLI entry point."""

from __future__ import annotations

import typer
from rich.console import Console

from vibeshorts import __version__
from vibeshorts.cli.commands import chat, config_cmd, create, init, render, studio

console = Console()

app = typer.Typer(
    name="vibeshorts",
    help="AI-native video editor — agents, MCP, Antigravity SDK, GCP Vertex",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"vibeshorts {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """VibeShorts — AI-native video editor CLI."""
    pass

init.register(app)
create.register(app)
render.register(app)
studio.register(app)
config_cmd.register(app)
chat.register(app)


if __name__ == "__main__":
    app()
