"""Only typed timelines are accepted. Arbitrary HTML/JS is never an API input."""
# ruff: noqa: E501

import hashlib
import html
import io
import json
import zipfile
from pathlib import Path, PurePosixPath

from execution.paths import NODE_MODULES
from tools.contracts.errors import AppError
from tools.contracts.studio import Composition

RUNTIME = {"hyperframes": "0.8.116", "gsap": "3.15.0", "schema": 1}


def markup(spec, paths):
    width, height = (720, 1280) if spec.aspect_ratio == "9:16" else (1280, 720)
    clips, motions = [], []
    for c in spec.clips:
        attrs = f'id="{c.id}" class="clip" data-start="{c.start}" data-duration="{c.duration}" data-track-index="{c.track}"'
        if c.hidden:
            attrs += ' data-hidden="true"'
        if c.kind == "text":
            clips.append(
                f'<div {attrs} style="z-index:{10 + c.track};position:absolute;inset:0;display:flex;align-items:flex-end;padding:110px 55px;font-size:56px;line-height:1.12;font-weight:700;overflow-wrap:break-word;text-shadow:0 2px 8px #000">{html.escape(c.text)}</div>'
            )
            motions.append(
                f'tl.fromTo("#{c.id}",{{y:24,opacity:0}},{{y:0,opacity:1,duration:0.4}}, {c.start});'
            )
        elif c.kind == "image":
            image_style = (
                "position:absolute;right:50px;top:65px;width:160px;height:100px;object-fit:contain;"
                if c.id == "brand-logo"
                else "position:absolute;inset:0;width:100%;height:100%;object-fit:cover;"
            )
            clips.append(
                f'<img {attrs} src="{paths[c.artifact_id]}" style="{image_style}z-index:{c.track}"/>'
            )
        elif c.kind == "video":
            clips.append(
                f'<video {attrs} src="{paths[c.artifact_id]}" data-media-start="{c.source_in}" data-volume="0" muted playsinline style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:{c.track}"></video>'
            )
            if c.volume > 0:
                clips.append(
                    f'<audio id="{c.id}-audio" class="clip" data-start="{c.start}" data-duration="{c.duration}" '
                    f'data-track-index="{c.track}" src="{paths[c.artifact_id]}" '
                    f'data-media-start="{c.source_in}" data-volume="{c.volume}"></audio>'
                )
        else:
            automation = html.escape(
                json.dumps(
                    {
                        "version": 1,
                        "lanes": [
                            {
                                "target": "volume",
                                "points": [
                                    {"t": 0, "v": 0 if c.fade_in else c.volume},
                                    {"t": c.fade_in, "v": c.volume},
                                    {"t": max(c.fade_in, c.duration - c.fade_out), "v": c.volume},
                                    {"t": c.duration, "v": 0 if c.fade_out else c.volume},
                                ],
                            }
                        ],
                    }
                ),
                quote=True,
            )
            clips.append(
                f'<audio {attrs} src="{paths[c.artifact_id]}" data-media-start="{c.source_in}" data-volume="{c.volume}" data-automation="{automation}"></audio>'
            )
    font_css = '@font-face{font-family:"Inter";src:url("assets/inter.woff2");font-weight:400} '
    if spec.fonts:
        font_id = spec.fonts.get("heading") or next(iter(spec.fonts.values()))
        font_css += '@font-face{font-family:"VibeShortsBrand";src:url("' + paths[font_id] + '")} '
    font_name = '"VibeShortsBrand",sans-serif' if spec.fonts else '"Inter",sans-serif'
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; frame-src 'none'; base-uri 'none'; form-action 'none'"><title>{html.escape(spec.title)}</title>
<style>{font_css}html,body{{margin:0;width:100%;height:100%;overflow:hidden}}*{{box-sizing:border-box}}#root{{width:100%;height:100%;position:relative;background:{spec.background};color:{spec.foreground};font-family:{font_name}}}video,img{{display:block}}</style><script src="assets/gsap.min.js"></script></head><body>
<div id="root" data-composition-id="vibeshorts" data-width="{width}" data-height="{height}" data-duration="{spec.duration_seconds}">{"".join(clips)}</div>
<script>const tl=gsap.timeline({{paused:true}});{"".join(motions)}window.__timelines["vibeshorts"]=tl;</script></body></html>'''


def build(spec, media):
    files, paths = {}, {}
    for artifact_id, (data, mime) in media.items():
        suffix = {
            "video/mp4": "mp4",
            "audio/wav": "wav",
            "audio/mpeg": "mp3",
            "image/png": "png",
            "image/jpeg": "jpg",
            "font/woff2": "woff2",
            "font/ttf": "ttf",
        }[mime]
        paths[artifact_id] = "assets/" + artifact_id + "." + suffix
        files[paths[artifact_id]] = data
    files["assets/inter.woff2"] = (
        NODE_MODULES / "@fontsource/inter/files/inter-latin-400-normal.woff2"
    ).read_bytes()
    files["assets/gsap.min.js"] = (NODE_MODULES / "gsap/dist/gsap.min.js").read_bytes()
    files["assets/runtime.iife.js"] = (
        NODE_MODULES / "@hyperframes/core/dist/hyperframe.runtime.iife.js"
    ).read_bytes()
    files["index.html"] = (
        markup(spec, paths)
        .replace(
            '<script src="assets/gsap.min.js"></script>',
            '<script src="assets/gsap.min.js"></script><script src="assets/runtime.iife.js"></script>',
        )
        .encode()
    )
    files["timeline.json"] = spec.model_dump_json().encode()
    files["runtime-lock.json"] = json.dumps(RUNTIME, sort_keys=True).encode()
    files["hyperframes.json"] = json.dumps({"name": "vibeshorts", "entry": "index.html"}).encode()
    manifest = {
        "schema_version": 1,
        "parent_id": spec.expected_head,
        "entrypoint": "index.html",
        "input_artifact_ids": sorted(media),
        "timeline": spec.model_dump(),
        "runtime_lock": RUNTIME,
        "output_profile": {
            "width": 720 if spec.aspect_ratio == "9:16" else 1280,
            "height": 1280 if spec.aspect_ratio == "9:16" else 720,
            "fps": 24,
            "duration_seconds": spec.duration_seconds,
        },
        "files": [{"path": p, "sha256": hashlib.sha256(d).hexdigest()} for p, d in sorted(files.items())],
    }
    files["manifest.json"] = json.dumps(manifest, sort_keys=True).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, data in sorted(files.items()):
            info = zipfile.ZipInfo(path, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


def unpack(data, destination=None):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            if (
                len(names) > 150
                or len(set(names)) != len(names)
                or sum(i.file_size for i in archive.infolist()) > 250_000_000
            ):
                raise ValueError("Package limit")
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or "\\" in name or not path.parts:
                    raise ValueError("Invalid path")
            files = {p: archive.read(p) for p in names}
            manifest = json.loads(files["manifest.json"])
            Composition.model_validate(manifest["timeline"])
            expected = {f["path"]: f["sha256"] for f in manifest["files"]}
            if set(expected) != set(files) - {"manifest.json"}:
                raise ValueError("Unexpected files")
            if any(hashlib.sha256(files[p]).hexdigest() != digest for p, digest in expected.items()):
                raise ValueError("Invalid file hash")
            if manifest["runtime_lock"] != RUNTIME:
                raise ValueError("Unsupported runtime lock")
            if destination:
                for path, content in files.items():
                    target = Path(destination) / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
            return manifest, files
    except (ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise AppError("INVALID_PACKAGE", "Invalid composition package") from exc
