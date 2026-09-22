"""MCP server configuration for GenMedia and custom tools."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from google.antigravity.types import McpStdioServer

from vibeshorts.config import VibeShortsConfig

GENMEDIA_SERVERS: dict[str, dict[str, Any]] = {
    "veo": {
        "command": "mcp-veo-go",
        "env": {
            "MCP_REQUEST_MAX_TOTAL_TIMEOUT": "240000",
            "MCP_SERVER_REQUEST_TIMEOUT": "30000",
        },
    },
    "imagen": {
        "command": "mcp-imagen-go",
        "env": {"MCP_SERVER_REQUEST_TIMEOUT": "55000"},
    },
    "chirp3-hd": {
        "command": "mcp-chirp3-go",
        "env": {"MCP_SERVER_REQUEST_TIMEOUT": "55000"},
    },
    "lyria": {
        "command": "mcp-lyria-go",
        "env": {"MCP_SERVER_REQUEST_TIMEOUT": "55000"},
    },
    "avtool": {
        "command": "mcp-avtool-go",
        "env": {"MCP_SERVER_REQUEST_TIMEOUT": "55000"},
    },
    "gemini": {
        "command": "mcp-gemini-go",
        "env": {
            "MCP_REQUEST_MAX_TOTAL_TIMEOUT": "120000",
            "MCP_SERVER_REQUEST_TIMEOUT": "55000",
        },
    },
}


def _merge_env(base: dict[str, str], config: VibeShortsConfig) -> dict[str, str]:
    merged = dict(base)
    merged["GOOGLE_CLOUD_PROJECT"] = config.gcp.project or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    bucket = config.gcp.genmedia_bucket or os.environ.get("GENMEDIA_BUCKET", "")
    if bucket:
        merged["GENMEDIA_BUCKET"] = bucket
    return merged


def build_genmedia_mcp_servers(
    config: VibeShortsConfig,
    enabled: list[str] | None = None,
) -> list[McpStdioServer]:
    """Build Antigravity MCP stdio servers for GenMedia tools."""
    if not config.integrations.enable_mcp_genmedia:
        return []

    server_names = enabled or list(GENMEDIA_SERVERS.keys())
    servers: list[McpStdioServer] = []

    for name in server_names:
        spec = GENMEDIA_SERVERS.get(name)
        if not spec:
            continue
        servers.append(
            McpStdioServer(
                name=name,
                command=spec["command"],
                env=_merge_env(spec.get("env", {}), config),
            )
        )
    return servers


def load_mcp_config(path: Path) -> list[McpStdioServer]:
    """Load MCP servers from a workspace mcp_config.json file."""
    if not path.exists():
        return []

    data = json.loads(path.read_text())
    servers: list[McpStdioServer] = []
    for name, spec in data.get("mcpServers", {}).items():
        servers.append(
            McpStdioServer(
                name=name,
                command=spec["command"],
                args=spec.get("args", []),
                env=spec.get("env"),
            )
        )
    return servers
