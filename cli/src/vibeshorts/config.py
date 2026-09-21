"""Configuration loading and project paths."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PACKAGE_ROOT / "config"
DEFAULT_PIPELINE = CONFIG_DIR / "pipeline" / "default.yaml"


class GcpConfig(BaseModel):
    project: str = Field(default="", description="Google Cloud project ID")
    location: str = Field(default="us-central1")
    genmedia_bucket: str = Field(default="", description="gs://bucket for generated media")
    use_vertex: bool = Field(default=True)


class AntigravityConfig(BaseModel):
    model: str = Field(default="gemini-2.5-flash")
    vertex: bool = Field(default=True)
    skills_paths: list[str] = Field(default_factory=list)
    mcp_config_path: str = Field(default=".agents/mcp_config.json")


class IntegrationsConfig(BaseModel):
    enable_mcp_genmedia: bool = Field(default=True)
    enable_veo: bool = Field(default=True)
    enable_lyria: bool = Field(default=True)
    enable_speech: bool = Field(default=True)
    hyperframes_bin: str = Field(default="npx")


class VibeShortsConfig(BaseModel):
    gcp: GcpConfig = Field(default_factory=GcpConfig)
    antigravity: AntigravityConfig = Field(default_factory=AntigravityConfig)
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)
    default_pipeline: str = Field(default=str(DEFAULT_PIPELINE))
    output_dir: str = Field(default="./renders")
    review_threshold: float = Field(default=0.65)
    max_retries: int = Field(default=2)


def _expand_env(value: str) -> str:
    if value.startswith("${") and value.endswith("}"):
        key = value[2:-1]
        return os.environ.get(key, "")
    return value


def _resolve_config_dict(data: dict[str, Any]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            resolved[key] = _resolve_config_dict(value)
        elif isinstance(value, str):
            resolved[key] = _expand_env(value)
        else:
            resolved[key] = value
    return resolved


def load_config(path: Path | None = None) -> VibeShortsConfig:
    """Load config from file or environment defaults."""
    config_path = path or Path(os.environ.get("VIBESHORTS_CONFIG", "vibeshorts.yaml"))
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text()) or {}
        raw = _resolve_config_dict(raw)
        return VibeShortsConfig.model_validate(raw)

    return VibeShortsConfig(
        gcp=GcpConfig(
            project=os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
            genmedia_bucket=os.environ.get("GENMEDIA_BUCKET", ""),
            use_vertex=os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "true").lower() == "true",
        ),
        antigravity=AntigravityConfig(
            model=os.environ.get("VIBESHORTS_MODEL", "gemini-2.5-flash"),
            vertex=os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "true").lower() == "true",
        ),
    )


def ensure_project_layout(project_dir: Path) -> dict[str, Path]:
    """Create standard VibeShorts project directories."""
    paths = {
        "root": project_dir,
        "footage": project_dir / "footage",
        "renders": project_dir / "renders",
        "timeline": project_dir / "timeline.json",
        "index": project_dir / "footage_index.json",
        "brief": project_dir / "brief.yaml",
        "agents": project_dir / ".agents",
        "skills": project_dir / ".agents" / "skills",
        "mcp_config": project_dir / ".agents" / "mcp_config.json",
        "hyperframes": project_dir / "composition",
    }
    for key, path in paths.items():
        if key in {"timeline", "index", "brief", "mcp_config"}:
            continue
        path.mkdir(parents=True, exist_ok=True)
    return paths


def write_mcp_config(project_dir: Path, config: VibeShortsConfig) -> Path:
    """Write GenMedia MCP config from template into the project."""
    template_path = CONFIG_DIR / "mcp_config.template.json"
    template = json.loads(template_path.read_text())
    project_id = config.gcp.project or os.environ.get("GOOGLE_CLOUD_PROJECT", "YOUR_PROJECT_ID")
    bucket = config.gcp.genmedia_bucket or os.environ.get("GENMEDIA_BUCKET", "gs://YOUR_BUCKET")

    for server in template.get("mcpServers", {}).values():
        env = server.setdefault("env", {})
        env["GOOGLE_CLOUD_PROJECT"] = project_id
        if "GENMEDIA_BUCKET" in env:
            env["GENMEDIA_BUCKET"] = bucket

    mcp_path = project_dir / ".agents" / "mcp_config.json"
    mcp_path.parent.mkdir(parents=True, exist_ok=True)
    mcp_path.write_text(json.dumps(template, indent=2))
    return mcp_path
