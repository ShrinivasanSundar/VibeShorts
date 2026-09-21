"""Footage preprocessing — scene detection and transcription."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from vibeshorts.models.schemas import FootageIndex, Shot, WordTimestamp

console = Console()
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


def _detect_roll_type(path: Path) -> str:
    name = path.name.lower()
    parent = path.parent.name.lower()
    if "broll" in name or "b-roll" in name or "broll" in parent:
        return "b-roll"
    if "aroll" in name or "a-roll" in name or "aroll" in parent:
        return "a-roll"
    return "unknown"


def _transcribe_whisper(video_path: Path) -> tuple[str, list[WordTimestamp]]:
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(video_path), word_timestamps=True)
        words: list[WordTimestamp] = []
        transcript_parts: list[str] = []
        for segment in segments:
            transcript_parts.append(segment.text.strip())
            if segment.words:
                for w in segment.words:
                    words.append(WordTimestamp(word=w.word.strip(), start=w.start, end=w.end))
        return " ".join(transcript_parts), words
    except ImportError:
        console.print("[yellow]faster-whisper not installed; skipping transcription[/]")
        return "", []


def _detect_scenes(video_path: Path) -> list[tuple[float, float]]:
    try:
        from scenedetect import detect, ContentDetector

        scene_list = detect(str(video_path), ContentDetector())
        if not scene_list:
            return [(0.0, _probe_duration(video_path))]
        return [(s[0].get_seconds(), s[1].get_seconds()) for s in scene_list]
    except ImportError:
        return [(0.0, _probe_duration(video_path))]


def _probe_duration(video_path: Path) -> float:
    import subprocess

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 30.0


def preprocess_footage(footage_dir: Path, use_whisper: bool = True) -> FootageIndex:
    """Build FootageIndex from a directory of raw clips."""
    index = FootageIndex()
    videos = sorted(
        p for p in footage_dir.rglob("*") if p.suffix.lower() in VIDEO_EXTENSIONS
    )

    if not videos:
        console.print(f"[red]No video files found in {footage_dir}[/]")
        return index

    for video_path in videos:
        console.print(f"[cyan]Processing[/] {video_path.name}")
        scenes = _detect_scenes(video_path)
        transcript, words = _transcribe_whisper(video_path) if use_whisper else ("", [])
        roll_type = _detect_roll_type(video_path)

        for i, (start, end) in enumerate(scenes):
            shot_words = [w for w in words if start <= w.start < end]
            shot = Shot(
                id=f"{video_path.name}#{start:.2f}",
                source_file=str(video_path.resolve()),
                start_time=start,
                end_time=end,
                transcript=transcript if len(scenes) == 1 else " ".join(w.word for w in shot_words),
                words=shot_words,
                roll_type=roll_type,
            )
            index.shots.append(shot)
            index.total_duration += end - start

    console.print(f"[green]Indexed {len(index.shots)} shots from {len(videos)} files[/]")
    return index
