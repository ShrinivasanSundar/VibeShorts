"""Resolve application resources independently of the process working directory."""

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
NODE_MODULES = REPO_ROOT / "node_modules"
