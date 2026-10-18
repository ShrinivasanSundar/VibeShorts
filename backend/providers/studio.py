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

from execution.paths import BACKEND_ROOT, NODE_MODULES
from providers.credentials import vertex_credentials
from providers.image import ImageOutput, ProviderFailure
from tools.composition.package import build, unpack
from tools.contracts.errors import AppError
from tools.contracts.models import Caller
from tools.contracts.studio import Composition, DirectorTurn, MusicInput, Scene, Storyboard
from tools.media.pipeline import extract, inspect, prepare, run

LOCAL = {"prepare", "frame", "composition", "render"}


def director_image(data):
    """A small JPEG the director can see. Session events store it, and Firestore caps documents at 1 MiB."""
    from PIL import Image

    image = Image.open(io.BytesIO(data))
    image.thumbnail((512, 512))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=80)
    return base64.b64encode(buffer.getvalue()).decode()


class StudioProvider:
    def __init__(self, commands, kind):
        self.commands, self.settings, self.kind = commands, commands.settings, kind

    def snapshot(self, request=None):
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
            "director_turn": s.director_model,
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
                "director_turn": "director_reservation_micros",
                "render": "render_per_call_micros",
            }[kind]
            unit_rate = rate.get(key)
            if kind == "video" and request is not None:
                profile = rate.get("video_rates", {}).get(models[kind], {})
                variant = request.resolution + (":audio" if request.generate_audio else ":no_audio")
                unit_rate = profile.get(variant, unit_rate)
            if not isinstance(unit_rate, int) or isinstance(unit_rate, bool) or unit_rate <= 0:
                raise AppError(
                    "RATE_REQUIRED",
                    f"{kind.capitalize()} generation requires a positive reviewed {key} "
                    "in VIBESHORTS_RATE_JSON",
                    503,
                )
            duration = request.source_duration_seconds if request is not None and kind == "video" else 8
            reservation = unit_rate * (duration if kind == "video" else 1)
        return {
            "route": route,
            "project": s.vertex_cloud_project if route == "vertex" else None,
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
            project=snapshot.get("project") or self.settings.google_cloud_project,
            location=snapshot["location"],
            credentials=vertex_credentials(self.settings),
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
                blob = (
                    storage.Client(
                        project=snapshot.get("project") or self.settings.google_cloud_project,
                        credentials=vertex_credentials(self.settings),
                    )
                    .bucket(bucket)
                    .blob(key)
                )
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

    def reference_images(self, request, job):
        """Attached images plus those the current storyboard already uses, at most three."""
        ids = list(request.reference_artifact_ids)
        story = getattr(request, "context", {}).get("storyboard") or {}
        for item in [*story.get("assets", []), *story.get("scenes", [])]:
            ids.extend(item.get("reference_artifact_ids", []))
        caller = Caller(**job["caller"])
        images = []
        for artifact_id in list(dict.fromkeys(ids))[:3]:
            data, _ = self.commands.asset_content(caller, job["project_id"], artifact_id)
            images.append({"artifact_id": artifact_id, "data": director_image(data)})
        return images

    def _director(self, request, snapshot, job, composition=None, images=()):
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
            "vertex_project": snapshot.get("project") or self.settings.google_cloud_project,
            "reference_images": list(images),
        }
        env = dict(os.environ)
        if snapshot["route"] == "vertex" and self.settings.vertex_credentials:
            env["VIBESHORTS_VERTEX_CREDENTIALS"] = self.settings.vertex_credentials
        if snapshot["route"] == "developer":
            env["VIBESHORTS_DIRECTOR_API_KEY"] = self.settings.developer_api_key
        try:
            result = subprocess.run(
                [self.settings.adk_python, str(BACKEND_ROOT / "agents/creative_director/direct.py")],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                timeout=90,
                env=env,
            )
        except (FileNotFoundError, PermissionError) as exc:
            # The child never started, so no provider request or charge is possible.
            raise ProviderFailure(
                "DIRECTOR_UNAVAILABLE",
                "Creative director could not start. Run: "
                "uv sync --project backend/agents/creative_director --frozen; "
                "check VIBESHORTS_ADK_PYTHON if configured.",
                retryable=True,
            ) from exc
        if result.returncode:
            from execution.director_recovery import director_failure
            from execution.telemetry import event

            event(
                "director_process_failed",
                job_id=job["job_id"],
                returncode=result.returncode,
                stderr=result.stderr[-2000:],
            )

            current = self.commands.repo.get(f"projects/{job['project_id']}/jobs/{job['job_id']}")
            usage = director_failure(self.commands.repo, current or job)
            if usage is not None:
                raise ProviderFailure(
                    "DIRECTOR_CALL_LIMIT",
                    "The director couldn’t finish its reply. Please retry your message.",
                    retryable=True,
                    usage=usage,
                )
            raise ProviderFailure("DIRECTOR_FAILED", "Director invocation failed", uncertain=True)
        return (
            DirectorTurn
            if self.kind == "director_turn"
            else Composition
            if self.kind == "edit"
            else Storyboard
        ).model_validate_json(result.stdout)

    def generate(self, request, references, snapshot, job):
        caller = Caller(**job["caller"])
        if self.kind == "director_turn":
            if snapshot["route"] == "fixture":
                from tools.conversation_fixture import fixture_turn

                turn = fixture_turn(request, job["project_id"], job["brand_version"])
            else:
                turn = self._director(request, snapshot, job, images=self.reference_images(request, job))
            return ImageOutput(turn.model_dump_json().encode(), "application/json")
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
                story = self._director(request, snapshot, job, images=self.reference_images(request, job))
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
            return self._music(request, snapshot, job)
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

                validate_submission(
                    self.commands,
                    caller,
                    job["project_id"],
                    "composition",
                    spec,
                    conversation_id=job.get("conversation_id"),
                )
            else:
                spec = request
            ids = sorted({c.artifact_id for c in spec.clips if c.artifact_id} | set(spec.fonts.values()))
            assets = {a: self.commands.asset_content(caller, job["project_id"], a) for a in ids}
            return ImageOutput(build(spec, assets), "application/zip")
        if self.kind == "render":
            return self._render(request, references[0])
        raise AppError("UNSUPPORTED_OPERATION", "Operation is unavailable")

    def _music(self, request, snapshot, job=None):
        if snapshot["route"] == "vertex":
            import google.auth
            from google.auth.transport.requests import AuthorizedSession

            credentials = vertex_credentials(self.settings)
            if credentials is None:
                credentials, _ = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
            location = snapshot["location"]
            host = (
                "aiplatform.googleapis.com"
                if location == "global"
                else location + "-aiplatform.googleapis.com"
            )
            project = snapshot.get("project") or self.settings.google_cloud_project
            url = (
                f"https://{host}/v1/projects/{project}/locations/{location}"
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
                body = response.json()
                if job:
                    self.commands.storage.put(
                        job["candidate_path"] + ".provider-response.json",
                        json.dumps(body).encode(),
                        {
                            "mime_type": "application/json",
                            "input_hash": job["input_hash"],
                            "attempt": job["attempt"],
                        },
                    )
                predictions = body.get("predictions") or []
                prediction = predictions[0] if predictions else {}
                encoded = prediction.get("audioContent") or prediction.get("bytesBase64Encoded")
                if not encoded:
                    from execution.telemetry import event

                    event(
                        "music_response_missing_audio",
                        response_fields=sorted(body),
                        prediction_fields=sorted(prediction),
                    )
                    raise ProviderFailure(
                        "MISSING_AUDIO", "Music response contained no audio", uncertain=True
                    )
                data = base64.b64decode(encoded, validate=True)
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
                # Windows has no POSIX ids; Docker Desktop bind mounts are writable by the
                # container's unprivileged user, so no ownership change is needed there.
                host_uid = os.getuid() if hasattr(os, "getuid") else None
                render_uid = host_uid or 65532
                render_gid = os.getgid() if host_uid else 65532
                scratch = directory / ".render-tmp"
                scratch.mkdir()
                if host_uid == 0:
                    os.chown(directory, render_uid, render_gid)
                    os.chown(scratch, render_uid, render_gid)
                args = [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--read-only",
                    "--user",
                    f"{render_uid}:{render_gid}",
                    "-e",
                    "TMPDIR=/work/.render-tmp",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--pids-limit",
                    "512",
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
                    "--fps",
                    "24",
                    "--workers",
                    "1",
                    "--quality",
                    "draft" if request.quality == "draft" else "delivery",
                ]
            elif self.settings.render_runner == "local" and self.settings.mode == "emulator":
                args = [str(NODE_MODULES / ".bin/hyperframes"), *args]
            else:
                raise AppError("RENDER_UNAVAILABLE", "An isolated renderer must be configured", 503)
            env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(Path.home()),
                "HYPERFRAMES_TELEMETRY_DISABLED": "1",
                "HYPERFRAMES_NO_TELEMETRY": "1",
                "DO_NOT_TRACK": "1",
            }
            # Windows programs need these to locate system DLLs, sockets and the Docker config.
            for key in ("SYSTEMROOT", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "PROGRAMDATA"):
                if os.environ.get(key):
                    env[key] = os.environ[key]
            try:
                subprocess.run(args, check=True, capture_output=True, timeout=600, env=env)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
                from execution.telemetry import event

                stderr = getattr(exc, "stderr", None) or b""
                event(
                    "render_process_failed",
                    runner=self.settings.render_runner,
                    error=str(exc)[-500:],
                    stderr=stderr.decode(errors="replace")[-2000:] if isinstance(stderr, bytes) else stderr,
                )
                raise AppError("RENDER_FAILED", "The video renderer failed; see the worker log", 503) from exc
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
    if kind in {"composition", "edit", "storyboard", "director_turn"}:
        if kind == "director_turn":
            DirectorTurn.model_validate_json(data)
        elif kind == "storyboard":
            Storyboard.model_validate_json(data)
        else:
            unpack(data)
        return {
            "mime_type": mime,
            "size_bytes": len(data),
            "content_sha256": hashlib.sha256(data).hexdigest(),
        }
    return inspect(data, mime)
