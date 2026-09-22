"""ASS kinetic caption generation and burn-in."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from vibeshorts.models.schemas import WordTimestamp


def _write_ass(words: list[WordTimestamp], clip_start: float, clip_end: float, path: Path) -> None:
    visible = [w for w in words if clip_start <= w.start < clip_end]
    events = []
    for word in visible:
        rel_start = word.start - clip_start
        rel_end = word.end - clip_start
        events.append(
            f"Dialogue: 0,{_ts(rel_start)},{_ts(rel_end)},Default,,0,0,0,,"
            f"{{\\c&H4ACFFF&}}{word.word}"
        )

    content = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,2,40,40,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(events)
    path.write_text(content)


def _ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def burn_captions(
    input_video: Path,
    words: list[WordTimestamp],
    clip_start: float,
    clip_end: float,
    output: Path,
) -> Path:
    with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as tmp:
        ass_path = Path(tmp.name)
    _write_ass(words, clip_start, clip_end, ass_path)

    output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_video),
            "-vf",
            f"ass={ass_path}",
            "-c:a",
            "copy",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    ass_path.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"Caption burn failed: {result.stderr}")
    return output
