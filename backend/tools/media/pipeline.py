"""Bounded media operations on materialized bytes, never caller-controlled paths."""

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from execution.storage import inspect_image
from tools.contracts.errors import AppError

MAX_MEDIA = 200_000_000


def run(arguments, timeout=180):
    try:
        return subprocess.run(arguments, capture_output=True, check=True, timeout=timeout).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        raise AppError(
            "MEDIA_PROCESSING_FAILED", "Media processing failed or exceeded its limit", 422
        ) from exc


def inspect(data, mime):
    if mime in {"image/png", "image/jpeg"}:
        return inspect_image(data, mime)
    if not data or len(data) > MAX_MEDIA:
        raise AppError("INVALID_MEDIA", "Media exceeds the configured limit")
    with tempfile.TemporaryDirectory(prefix="vibeshorts-media-") as folder:
        path = Path(folder) / "source"
        path.write_bytes(data)
        facts = json.loads(
            run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(path),
                ],
                30,
            )
        )
        streams = facts.get("streams", [])
        duration = float(facts.get("format", {}).get("duration", 0))
        if not streams or not 0 < duration <= 125:
            raise AppError("INVALID_MEDIA", "Missing streams or unsupported duration")
        video = next((s for s in streams if s["codec_type"] == "video"), None)
        audio = next((s for s in streams if s["codec_type"] == "audio"), None)
        if mime == "video/mp4" and not video or mime.startswith("audio/") and not audio:
            raise AppError("INVALID_MEDIA", "Declared MIME does not match media streams")
        if mime == "video/mp4" and "mp4" not in facts["format"]["format_name"]:
            raise AppError("INVALID_MEDIA", "Video must be an MP4 container")
        if mime == "audio/mpeg" and facts["format"]["format_name"] != "mp3":
            raise AppError("INVALID_MEDIA", "Audio must be an MP3 container")
        if mime == "audio/wav" and facts["format"]["format_name"] != "wav":
            raise AppError("INVALID_MEDIA", "Audio must be a WAV container")
        if video and (video.get("width", 0) > 4096 or video.get("height", 0) > 4096):
            raise AppError("INVALID_MEDIA", "Dimensions exceed the render limit")
        rate = (video or {}).get("avg_frame_rate", "0/1").split("/")
        return {
            "mime_type": mime,
            "size_bytes": len(data),
            "content_sha256": hashlib.sha256(data).hexdigest(),
            "duration_seconds": duration,
            "width": (video or {}).get("width"),
            "height": (video or {}).get("height"),
            "fps": int(rate[0]) / max(1, int(rate[1])),
            "has_audio": bool(audio),
            "sample_rate": int(audio.get("sample_rate", 0)) if audio else None,
            "streams": [
                {k: s.get(k) for k in ("codec_type", "codec_name", "sample_rate", "channels")}
                for s in streams
            ],
        }


def prepare(data, mime, request):
    facts = inspect(data, mime)
    if request.out_seconds > facts["duration_seconds"] + 0.05:
        raise AppError("INVALID_INPUT", "Trim exceeds source duration")
    with tempfile.TemporaryDirectory(prefix="vibeshorts-prepare-") as folder:
        source, output = Path(folder) / "source", Path(folder) / "output"
        source.write_bytes(data)
        args = [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(source),
            "-ss",
            str(request.in_seconds),
            "-t",
            str(request.out_seconds - request.in_seconds),
        ]
        if mime.startswith("audio/"):
            duration = request.out_seconds - request.in_seconds
            args += [
                "-vn",
                "-af",
                (
                    "loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:d=0.4,"
                    f"afade=t=out:st={max(0, duration - 0.7)}:d=0.7"
                ),
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                "-f",
                "wav",
            ]
            result_mime = "audio/wav"
        else:
            w, h = (720, 1280) if request.aspect_ratio == "9:16" else (1280, 720)
            args += [
                "-vf",
                f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps=24",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-pix_fmt",
                "yuv420p",
                "-threads",
                "2",
            ]
            args += ["-an"] if request.mute else ["-c:a", "aac", "-ar", "48000", "-ac", "2"]
            args += ["-movflags", "+faststart", "-f", "mp4"]
            result_mime = "video/mp4"
        run(args + ["-y", str(output)])
        return output.read_bytes(), result_mime


def extract(data, mime, frame_index):
    facts = inspect(data, mime)
    if not facts.get("fps") or frame_index >= int(facts["duration_seconds"] * facts["fps"]):
        raise AppError("INVALID_INPUT", "Frame lies outside the source")
    with tempfile.TemporaryDirectory(prefix="vibeshorts-frame-") as folder:
        source, output = Path(folder) / "source", Path(folder) / "frame.png"
        source.write_bytes(data)
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(source),
                "-vf",
                f"select=eq(n\\,{frame_index})",
                "-frames:v",
                "1",
                "-y",
                str(output),
            ]
        )
        return output.read_bytes()


def inspect_upload(data, mime):
    if mime.startswith("image/"):
        return inspect_image(data, mime, 7_000_000)
    if mime.startswith("font/"):
        if len(data) > 2_000_000:
            raise AppError("INVALID_MEDIA", "Font exceeds the 2 MB limit")
        try:
            import io

            from fontTools.ttLib import TTFont

            with TTFont(io.BytesIO(data), lazy=False) as font:
                if (mime == "font/woff2") != (font.flavor == "woff2"):
                    raise ValueError("Font MIME mismatch")
                if not font.getBestCmap() or font["maxp"].numGlyphs > 65535:
                    raise ValueError("Invalid font")
                for tag in font.keys():
                    _ = font[tag]
        except Exception as exc:
            raise AppError("INVALID_MEDIA", "Invalid or unsupported font") from exc
        return {
            "mime_type": mime,
            "size_bytes": len(data),
            "content_sha256": hashlib.sha256(data).hexdigest(),
        }
    return inspect(data, mime)
