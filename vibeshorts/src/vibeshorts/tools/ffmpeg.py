"""FFmpeg wrappers for deterministic video editing."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr}")


def extract_clip(source: Path, start: float, end: float, output: Path) -> Path:
    duration = max(0.1, end - start)
    output.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            str(start),
            "-i",
            str(source),
            "-t",
            str(duration),
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            str(output),
        ]
    )
    return output


def extract_probe_clip(source: Path, start: float, end: float, output: Path) -> Path:
    return extract_clip(source, start, end, output)


def concat_clips(
    clips: list[Path],
    output: Path,
    music_path: Path | None = None,
) -> Path:
    if not clips:
        raise ValueError("No clips to concatenate")

    output.parent.mkdir(parents=True, exist_ok=True)
    list_file = output.parent / "concat_list.txt"
    list_file.write_text("\n".join(f"file '{c.resolve()}'" for c in clips))

    if music_path and music_path.exists():
        _run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-i",
                str(music_path),
                "-filter_complex",
                "[1:a]volume=0.15[music];[0:a][music]amix=inputs=2:duration=first[aout]",
                "-map",
                "0:v",
                "-map",
                "[aout]",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-shortest",
                str(output),
            ]
        )
    else:
        _run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                str(output),
            ]
        )
    return output
