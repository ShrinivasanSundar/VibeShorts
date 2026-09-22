"""vibeshorts config — show and validate configuration."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from vibeshorts.config import CONFIG_DIR, load_config, write_mcp_config
from vibeshorts.integrations.mcp import build_genmedia_mcp_servers

console = Console()


def register(app: typer.Typer) -> None:
    config_app = typer.Typer(help="Configuration management")
    app.add_typer(config_app, name="config")

    @config_app.command("show")
    def show(config_path: Path = typer.Option(None, "--config", "-c")) -> None:
        """Display current VibeShorts configuration."""
        config = load_config(config_path)
        console.print_json(config.model_dump_json())

    @config_app.command("validate")
    def validate(
        project_dir: Path = typer.Option(Path("."), "--project", "-p"),
        config_path: Path = typer.Option(None, "--config", "-c"),
    ) -> None:
        """Validate GCP, MCP, and integration settings."""
        config = load_config(config_path)
        table = Table(title="VibeShorts Integration Status")
        table.add_column("Integration")
        table.add_column("Status")
        table.add_column("Details")

        checks = [
            ("GCP Project", bool(config.gcp.project), config.gcp.project or "Not set"),
            ("GCP Location", True, config.gcp.location),
            ("GenMedia Bucket", bool(config.gcp.genmedia_bucket), config.gcp.genmedia_bucket or "Not set"),
            ("Vertex AI", config.gcp.use_vertex, "enabled" if config.gcp.use_vertex else "disabled"),
            ("MCP GenMedia", config.integrations.enable_mcp_genmedia, f"{len(build_genmedia_mcp_servers(config))} servers"),
            ("Veo", config.integrations.enable_veo, "enabled"),
            ("Lyria", config.integrations.enable_lyria, "enabled"),
            ("Speech", config.integrations.enable_speech, "enabled"),
            ("Antigravity Model", True, config.antigravity.model),
        ]
        for name, ok, detail in checks:
            status = "[green]OK[/]" if ok else "[yellow]WARN[/]"
            table.add_row(name, status, detail)

        console.print(table)

    @config_app.command("mcp")
    def mcp(
        project_dir: Path = typer.Option(Path("."), "--project", "-p"),
        config_path: Path = typer.Option(None, "--config", "-c"),
    ) -> None:
        """Generate .agents/mcp_config.json for GenMedia MCP servers."""
        config = load_config(config_path)
        path = write_mcp_config(project_dir.resolve(), config)
        console.print(f"[green]Wrote MCP config:[/] {path}")

        servers = build_genmedia_mcp_servers(config)
        console.print(f"Configured {len(servers)} GenMedia MCP servers:")
        for s in servers:
            console.print(f"  - {s.name}: {s.command}")
