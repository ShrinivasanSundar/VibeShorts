"""Hyperframes render integration."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def render_hyperframes(
    composition_dir: Path,
    output: Path,
    bin_prefix: str = "npx",
    quality: str = "high",
) -> Path:
    if not composition_dir.exists():
        raise FileNotFoundError(
            f"Hyperframes composition not found at {composition_dir}. "
            "Run `vibeshorts init` to scaffold the project."
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        bin_prefix,
        "hyperframes",
        "render",
        "--quality",
        quality,
        "--output",
        str(output),
        str(composition_dir),
    ]

    if shutil.which("hyperframes"):
        cmd = ["hyperframes", "render", "--quality", quality, "--output", str(output), str(composition_dir)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Hyperframes render failed: {result.stderr}")
    return output
