"""vibeshorts init — scaffold a new project."""

from __future__ import annotations

import shutil
from pathlib import Path

import typer
from rich.console import Console

from vibeshorts.config import CONFIG_DIR, ensure_project_layout, load_config, write_mcp_config

console = Console()


def register(app: typer.Typer) -> None:
    @app.command("init")
    def init(
        project_dir: Path = typer.Argument(Path("."), help="Project directory to initialize"),
        config_path: Path = typer.Option(None, "--config", "-c"),
    ) -> None:
        """Initialize a VibeShorts project with MCP, skills, and config."""
        config = load_config(config_path)
        project_dir = project_dir.resolve()
        paths = ensure_project_layout(project_dir)

        template_config = CONFIG_DIR / "vibeshorts.yaml.template"
        dest_config = project_dir / "vibeshorts.yaml"
        if not dest_config.exists() and template_config.exists():
            shutil.copy(template_config, dest_config)
            console.print(f"  Created {dest_config}")

        mcp_path = write_mcp_config(project_dir, config)
        console.print(f"  Created {mcp_path}")

        skills_src = CONFIG_DIR.parent / "skills"
        skills_dest = paths["skills"]
        if skills_src.exists():
            for skill_dir in skills_src.iterdir():
                if skill_dir.is_dir():
                    target = skills_dest / skill_dir.name
                    if not target.exists():
                        shutil.copytree(skill_dir, target)
            console.print(f"  Installed skills to {skills_dest}")

        brief_template = CONFIG_DIR / "brief.template.yaml"
        if brief_template.exists() and not paths["brief"].exists():
            shutil.copy(brief_template, paths["brief"])

        hf_index = paths["hyperframes"] / "index.html"
        if not hf_index.exists():
            hf_index.write_text(_default_hyperframes_html())

        console.print(f"\n[bold green]VibeShorts project initialized at {project_dir}[/]")
        console.print("\nNext steps:")
        console.print("  1. Set GOOGLE_CLOUD_PROJECT and GENMEDIA_BUCKET in vibeshorts.yaml")
        console.print("  2. Add raw clips to ./footage/")
        console.print("  3. Edit ./brief.yaml")
        console.print("  4. Run: vibeshorts create --footage ./footage --brief ./brief.yaml")


def _default_hyperframes_html() -> str:
    return """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>VibeShorts Composition</title>
  <style>
    body { margin: 0; background: #000; }
    video { width: 100vw; height: 100vh; object-fit: cover; }
    .caption { position: absolute; bottom: 15%; width: 100%; text-align: center;
               font-family: Montserrat, sans-serif; font-size: 48px; color: #fff; }
  </style>
</head>
<body data-fps="30" data-width="1080" data-height="1920">
  <video id="main" src="../renders/final.mp4" muted></video>
  <div class="caption" id="caption"></div>
  <script>
    // Timeline sync driven by timeline.json at render time
    const video = document.getElementById('main');
    video.play();
  </script>
</body>
</html>
"""
