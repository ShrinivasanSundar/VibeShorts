"""Explicit media routes and isolated deterministic composition execution."""

import base64
import hashlib
import io
import json
import math
import os
import subprocess
import tempfile
import wave
from pathlib import Path

from providers.image import ImageOutput, ProviderFailure
from tools.composition.package import build, unpack
from tools.contracts.errors import AppError
from tools.contracts.models import Caller
from tools.contracts.studio import Composition, MusicInput, Scene, Storyboard
from tools.media.pipeline import extract, inspect, prepare, run

LOCAL = {"prepare", "frame", "composition", "render"}


class StudioProvider:
    def __init__(self, commands, kind):
        self.commands, self.settings, self.kind = commands, commands.settings, kind

    def snapshot(self):
        s, kind = self.settings, self.kind
        route = (
            "cloud_run"
            if kind == "render" and s.render_runner == "cloud_run"
            else ("local" if kind in LOCAL else s.provider)
        )
        rate = json.loads(s.rate_json or "{}")
        models = {
            "video": s.video_model if route != "developer" else s.developer_video_model,
            "music": s.music_model if route != "developer" else s.developer_music_model,
            "storyboard": s.director_model,
            "edit": s.director_model,
        }
        reservation = 0
        if route in {"vertex", "developer", "cloud_run"}:
            if s.paid_allowance_micros <= 0:
                raise AppError(
                    "ALLOWANCE_REQUIRED", "Paid execution requires a positive server allowance", 503
                )
            key = {
                "video": "video_per_second_micros",
                "music": "music_per_call_micros",
                "storyboard": "director_reservation_micros",
                "edit": "director_reservation_micros",
                "render": "render_per_call_micros",
            }[kind]
            if not isinstance(rate.get(key), int) or rate[key] <= 0:
                raise AppError("RATE_REQUIRED", "Configure a positive reviewed rate for this operation", 503)
            reservation = rate[key] * (8 if kind == "video" else 1)
        return {
            "route": route,
            "model": models.get(kind, "hyperframes-0.8.116" if kind == "render" else kind),
            "location": s.video_location
            if kind == "video"
            else s.music_location
            if kind == "music"
            else s.google_location,
            "api_version": "v1beta" if route == "developer" else "v1",
            "profile_version": "media-v1",
            "rate": rate,
            "render_cloud_job": s.render_cloud_job if kind == "render" else None,
            "reservation_micros": reservation,
        }

    def cost(self, usage, snapshot):
        if snapshot["route"] in {"fixture", "local"}:
            return 0, snapshot["route"]
        # Reservations remain conservative estimates until a billing reconciliation confirms costs.
        return snapshot["reservation_micros"], "estimated"

    def client(self, snapshot):
        from google import genai
        from google.genai import types

        options = types.HttpOptions(timeout=90_000, retry_options=types.HttpRetryOptions(attempts=1))
        if snapshot["route"] == "developer":
            return genai.Client(api_key=self.settings.developer_api_key, http_options=options)
        return genai.Client(
            vertexai=True,
            project=self.settings.google_cloud_project,
            location=snapshot["location"],
            http_options=options,
        )

    def submit_video(self, request, first_frame, snapshot):
        from google.genai import types

        from execution.storage import inspect_image

        client = self.client(snapshot)
        try:
            operation = client.models.generate_videos(
                model=snapshot["model"],
                prompt=request.prompt,
                image=types.Image(image_bytes=first_frame, mime_type=inspect_image(first_frame)["mime_type"]),
                config=types.GenerateVideosConfig(
                    aspect_ratio=request.aspect_ratio,
                    duration_seconds=request.source_duration_seconds,
                    resolution=request.resolution,
                    generate_audio=request.generate_audio,
                ),
            )
            if not operation.name:
                raise ProviderFailure(
                    "MISSING_OPERATION", "Provider omitted its operation handle", uncertain=True
                )
            return {"name": operation.name, "done": False}
        except ProviderFailure:
            raise
        except Exception as exc:
            code = getattr(exc, "code", None)
            definitive = isinstance(code, int) and 400 <= code < 500
            raise ProviderFailure(
                "VIDEO_SUBMISSION_FAILED", "Video submission failed", uncertain=not definitive
            ) from exc
        finally:
            client.close()

    def poll_video(self, operation, snapshot):
        from google.genai import types

        client = self.client(snapshot)
        try:
            result = client.operations.get(types.GenerateVideosOperation.model_validate(operation))
            if not result.done:
                return None, {"name": result.name, "done": False}
            if result.error:
                raise ProviderFailure("VIDEO_FAILED", "Provider operation failed")
            videos = result.response.generated_videos if result.response else None
            if not videos:
                raise ProviderFailure("FILTERED_RESPONSE", "Provider returned no video")
            video = videos[0].video
            data = video.video_bytes
            if not data and video.uri and video.uri.startswith("gs://"):
                from google.cloud import storage

                bucket, key = video.uri[5:].split("/", 1)
                blob = storage.Client(project=self.settings.google_cloud_project).bucket(bucket).blob(key)
                blob.reload()
                if blob.size > self.settings.max_media_bytes:
                    raise ProviderFailure("INVALID_MEDIA", "Provider video exceeds media limit")
                data = blob.download_as_bytes(if_generation_match=blob.generation)
            elif not data:
                data = client.files.download(file=video)
            if not data:
                raise ProviderFailure("MISSING_VIDEO", "Provider video is empty")
            return ImageOutput(data, "video/mp4"), {"name": result.name, "done": True}
        finally:
            client.close()

    def submit_render(self, request, job):
        from providers.render_cloud import submit

        return submit(self.commands, request, job)

    def poll_render(self, operation):
        from providers.render_cloud import poll

        return poll(self.commands, operation)

    def _director(self, request, snapshot, job, composition=None):
        payload = {
            "operation": self.kind,
            "request": request.model_dump(),
            "composition": composition,
            "uid": job["caller"]["uid"],
            "project_id": job["project_id"],
            "run_id": job["run_id"],
            "job_id": job["job_id"],
            "brand_version": job["brand_version"],
            "route": snapshot["route"],
            "model": snapshot["model"],
            "location": snapshot["location"],
            "cloud_project": self.settings.google_cloud_project,
        }
        env = dict(os.environ)
        if snapshot["route"] == "developer":
            env["VIBESHORTS_DIRECTOR_API_KEY"] = self.settings.developer_api_key
        result = subprocess.run(
            [self.settings.adk_python, "agents/creative_director/direct.py"],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=90,
            env=env,
        )
        if result.returncode:
            raise ProviderFailure("DIRECTOR_FAILED", "Director invocation failed", uncertain=True)
        return (Composition if self.kind == "edit" else Storyboard).model_validate_json(result.stdout)

    def generate(self, request, references, snapshot, job):
        caller = Caller(**job["caller"])
        if self.kind == "storyboard":
            if job.get("storyboard_override"):
                story = Storyboard.model_validate(job["storyboard_override"])
            elif snapshot["route"] == "fixture":
                count = max(3, min(5, math.ceil(request.duration_seconds / 8)))
                labels = [
                    "Introducing",
                    "Made for you",
                    "Discover more",
                    "Designed to delight",
                    "Get started",
                ]
                if request.locale == "es":
                    labels = [
                        "Presentamos",
                        "Hecho para ti",
                        "Descubre más",
                        "Diseñado para inspirar",
                        "Comienza ahora",
                    ]
                if request.locale == "hi":
                    labels = ["परिचय", "आपके लिए", "और जानें", "नई शुरुआत", "आज शुरू करें"]
                story = Storyboard(
                    project_id=job["project_id"],
                    brand_version=job["brand_version"],
                    skill_version=request.policy + "@1.0",
                    aspect_ratio=request.aspect_ratio,
                    duration_seconds=request.duration_seconds,
                    scenes=[
                        Scene(
                            id=f"scene-{i + 1}",
                            objective=labels[i],
                            exact_copy=[labels[i]],
                            editorial_duration_seconds=request.duration_seconds / count,
                            visual_prompt=request.brief + f". Scene {i + 1}: {labels[i]}. No text, no logos.",
                            reference_artifact_ids=request.reference_artifact_ids,
                        )
                        for i in range(count)
                    ],
                    music=MusicInput(prompt="Instrumental uplifting product launch, no vocals"),
                )
            else:
                story = self._director(request, snapshot, job)
            return ImageOutput(story.model_dump_json().encode(), "application/json")
        if self.kind == "video":
            with tempfile.TemporaryDirectory() as folder:
                source, output = Path(folder) / "frame.png", Path(folder) / "video.mp4"
                source.write_bytes(references[0])
                w, h = (720, 1280) if request.aspect_ratio == "9:16" else (1280, 720)
                run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-nostdin",
                        "-loop",
                        "1",
                        "-i",
                        str(source),
                        "-t",
                        str(request.source_duration_seconds),
                        "-vf",
                        f"scale={w}:{h},fps=24",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-threads",
                        "2",
                        "-y",
                        str(output),
                    ]
                )
                return ImageOutput(output.read_bytes(), "video/mp4")
        if self.kind == "music":
            if snapshot["route"] == "fixture":
                from array import array

                samples = array("h")
                for i in range(int(48000 * request.duration_seconds)):
                    t = i / 48000
                    gain = min(1, t / 0.4, (request.duration_seconds - t) / 0.7)
                    v = int(1200 * gain * (math.sin(2 * math.pi * 220 * t) + math.sin(2 * math.pi * 330 * t)))
                    samples.extend([v, v])
                buffer = io.BytesIO()
                with wave.open(buffer, "wb") as out:
                    out.setnchannels(2)
                    out.setsampwidth(2)
                    out.setframerate(48000)
                    out.writeframes(samples.tobytes())
                return ImageOutput(buffer.getvalue(), "audio/wav")
            return self._music(request, snapshot)
        if self.kind in {"prepare", "frame"}:
            _, mime = self.commands.asset_content(caller, job["project_id"], request.artifact_id)
            if self.kind == "frame":
                return ImageOutput(extract(references[0], mime, request.frame_index), "image/png")
            data, mime = prepare(references[0], mime, request)
            return ImageOutput(data, mime)
        if self.kind in {"composition", "edit"}:
            if self.kind == "edit":
                manifest, _ = unpack(references[0])
                previous = Composition.model_validate(manifest["timeline"])
                if snapshot["route"] == "fixture":
                    from tools.composition.edits import fixture_edit

                    spec = fixture_edit(previous, request.instruction)
                else:
                    spec = self._director(request, snapshot, job, previous.model_dump())
                spec.expected_head = request.expected_head
                from tools.studio_commands import validate_submission

                validate_submission(self.commands, caller, job["project_id"], "composition", spec)
            else:
                spec = request
            ids = sorted({c.artifact_id for c in spec.clips if c.artifact_id} | set(spec.fonts.values()))
            assets = {a: self.commands.asset_content(caller, job["project_id"], a) for a in ids}
            return ImageOutput(build(spec, assets), "application/zip")
        if self.kind == "render":
            return self._render(request, references[0])
        raise AppError("UNSUPPORTED_OPERATION", "Operation is unavailable")

    def _music(self, request, snapshot):
        if snapshot["route"] == "vertex":
            import google.auth
            from google.auth.transport.requests import AuthorizedSession

            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            location = snapshot["location"]
            host = (
                "aiplatform.googleapis.com"
                if location == "global"
                else location + "-aiplatform.googleapis.com"
            )
            url = (
                f"https://{host}/v1/projects/{self.settings.google_cloud_project}/locations/{location}"
                f"/publishers/google/models/{snapshot['model']}:predict"
            )
            session = AuthorizedSession(credentials)
            try:
                response = session.post(
                    url,
                    json={"instances": [{"prompt": request.prompt}], "parameters": {"sample_count": 1}},
                    timeout=90,
                )
                if response.status_code >= 400:
                    raise ProviderFailure(
                        "MUSIC_FAILED",
                        "Music provider rejected the request",
                        uncertain=response.status_code >= 500,
                    )
                data = base64.b64decode(response.json()["predictions"][0]["audioContent"], validate=True)
                return ImageOutput(data, "audio/wav")
            finally:
                session.close()
        import httpx

        response = httpx.post(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            headers={"x-goog-api-key": self.settings.developer_api_key},
            json={"model": snapshot["model"], "input": request.prompt},
            timeout=90,
        )
        if response.status_code >= 400:
            raise ProviderFailure(
                "MUSIC_FAILED", "Music provider rejected the request", uncertain=response.status_code >= 500
            )
        outputs = response.json().get("outputs", [])
        audio = next((o for o in outputs if o.get("type") == "audio"), None)
        if not audio or not audio.get("data"):
            raise ProviderFailure("MISSING_AUDIO", "Music provider returned no audio", uncertain=True)
        return ImageOutput(
            base64.b64decode(audio["data"], validate=True), audio.get("mime_type", "audio/mpeg")
        )

    def _render(self, request, data):
        manifest, files = unpack(data)
        with tempfile.TemporaryDirectory(prefix="vibeshorts-render-") as folder:
            directory = Path(folder)
            for name, content in files.items():
                path = directory / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            output = directory / "result.mp4"
            args = [
                "render",
                str(directory),
                "--output",
                str(output),
                "--fps",
                "24",
                "--quality",
                "draft" if request.quality == "draft" else "delivery",
            ]
            if self.settings.render_runner == "docker":
                args = [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--pids-limit",
                    "256",
                    "--memory",
                    "4g",
                    "--cpus",
                    "2",
                    "--tmpfs",
                    "/tmp:rw,size=1g",
                    "-v",
                    f"{directory}:/work:rw",
                    self.settings.render_image,
                    "render",
                    "/work",
                    "--output",
                    "/work/result.mp4",
                    "--browser-path",
                    "/usr/local/bin/hyperframes-chrome",
                    "--fps",
                    "24",
                    "--quality",
                    "draft" if request.quality == "draft" else "delivery",
                ]
            elif self.settings.render_runner == "local" and self.settings.mode == "emulator":
                args = [str(Path("node_modules/.bin/hyperframes").resolve()), *args]
            else:
                raise AppError("RENDER_UNAVAILABLE", "An isolated renderer must be configured", 503)
            env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(Path.home()),
                "HYPERFRAMES_TELEMETRY_DISABLED": "1",
            }
            subprocess.run(args, check=True, capture_output=True, timeout=600, env=env)
            result = output.read_bytes()
            facts = inspect(result, "video/mp4")
            profile = manifest["output_profile"]
            if abs(facts["duration_seconds"] - profile["duration_seconds"]) > 0.15:
                raise AppError("INVALID_RENDER", "Render duration does not match the composition")
            if (facts["width"], facts["height"], round(facts["fps"])) != (
                profile["width"],
                profile["height"],
                24,
            ):
                raise AppError("INVALID_RENDER", "Render dimensions or frame rate are invalid")
            audible = any(
                c["kind"] in {"audio", "video"} and c["volume"] > 0 and not c["hidden"]
                for c in manifest["timeline"]["clips"]
            )
            if audible and not facts["has_audio"]:
                raise AppError("INVALID_RENDER", "Render omitted audible media")
            return ImageOutput(result, "video/mp4")


def inspect_output(kind, data, mime):
    if kind in {"composition", "edit", "storyboard"}:
        if kind == "storyboard":
            Storyboard.model_validate_json(data)
        else:
            unpack(data)
        return {
            "mime_type": mime,
            "size_bytes": len(data),
            "content_sha256": hashlib.sha256(data).hexdigest(),
        }
    return inspect(data, mime)
