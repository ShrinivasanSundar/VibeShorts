import hashlib
import io
import math
from dataclasses import dataclass, field

from PIL import Image, ImageDraw

from execution.storage import inspect_image
from tools.contracts.errors import AppError


@dataclass
class ImageOutput:
    data: bytes
    mime_type: str
    usage: dict = field(default_factory=dict)


class ProviderFailure(AppError):
    def __init__(self, code: str, message: str, uncertain=False, retryable=False):
        self.uncertain = uncertain
        super().__init__(code, message, 503, retryable=retryable)


class FixtureImageProvider:
    calls = 0

    def snapshot(self):
        return {
            "route": "fixture",
            "model": "deterministic-image-v1",
            "location": "local",
            "api_version": "1",
            "profile_version": "fixture-v1",
            "launch_stage": "local",
            "verified_at": "2026-10-03",
            "rate": {"version": "fixture-v1"},
            "deprecated": False,
            "reservation_micros": 1000,
        }

    def generate(self, request, references, snapshot):
        self.calls += 1
        seed = hashlib.sha256(request.prompt.encode() + b"".join(references)).digest()
        dimensions = (180, 320) if request.aspect_ratio == "9:16" else (320, 180)
        image = Image.new("RGB", dimensions, tuple(seed[:3]))
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 20, dimensions[0] - 20, dimensions[1] - 20), outline="white", width=3)
        draw.text((30, 40), "VibeShorts\nFixture image", fill="white")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return ImageOutput(buffer.getvalue(), "image/png", {"input_tokens": 0, "output_tokens": 0})

    def cost(self, usage, snapshot):
        return 1000, "fixture"


class VertexImageProvider:
    def __init__(self, settings):
        self.settings = settings

    def snapshot(self):
        import json

        rate = json.loads(self.settings.rate_json)
        # Bound provider input/output tokens conservatively, including reference images.
        estimate = math.ceil(
            (32768 * rate["input_per_million_micros"] + 2048 * rate["output_per_million_micros"]) / 1_000_000
        )
        return {
            "route": self.settings.provider,
            "model": self.settings.image_model,
            "location": self.settings.google_location,
            "api_version": "v1beta" if self.settings.provider == "developer" else "v1",
            "profile_version": "vertex-image-v1",
            "verified_at": "2026-10-03",
            "launch_stage": "GA",
            "deprecated": self.settings.image_model == "gemini-2.5-flash-image",
            "rate": rate,
            "reservation_micros": estimate,
        }

    def generate(self, request, references, snapshot):
        from google import genai
        from google.genai import types

        route = (
            {"api_key": self.settings.developer_api_key}
            if snapshot["route"] == "developer"
            else {
                "vertexai": True,
                "project": self.settings.google_cloud_project,
                "location": snapshot["location"],
            }
        )
        client = genai.Client(
            **route,
            http_options=types.HttpOptions(
                api_version=snapshot["api_version"],
                timeout=self.settings.provider_timeout_seconds * 1000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        try:
            contents = [types.Part.from_text(text=request.prompt)]
            for data in references:
                media = inspect_image(data, limit=7_000_000)
                contents.append(types.Part.from_bytes(data=data, mime_type=media["mime_type"]))
            response = client.models.generate_content(
                model=snapshot["model"],
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    candidate_count=1,
                    max_output_tokens=2048,
                    image_config=types.ImageConfig(aspect_ratio=request.aspect_ratio),
                ),
            )
            candidates = response.candidates or []
            if (response.prompt_feedback and response.prompt_feedback.block_reason) or any(
                str(c.finish_reason) in {"FinishReason.SAFETY", "FinishReason.IMAGE_SAFETY"}
                for c in candidates
            ):
                raise ProviderFailure("SAFETY_REJECTED", "The provider rejected the requested content")
            parts = [
                p
                for c in candidates
                if c.content
                for p in (c.content.parts or [])
                if p.inline_data and p.inline_data.mime_type.startswith("image/")
            ]
            if len(parts) != 1:
                raise ProviderFailure(
                    "INVALID_PROVIDER_OUTPUT", "The provider did not return one image", uncertain=True
                )
            usage = response.usage_metadata
            return ImageOutput(
                parts[0].inline_data.data,
                parts[0].inline_data.mime_type,
                {
                    "input_tokens": usage.prompt_token_count or 0 if usage else None,
                    "output_tokens": usage.candidates_token_count or 0 if usage else None,
                },
            )
        except ProviderFailure:
            raise
        except Exception as exc:
            code = getattr(exc, "code", None)
            if code in {400, 401, 403, 404, 429}:
                raise ProviderFailure(
                    "PROVIDER_UNAVAILABLE", "Provider rejected the request", retryable=code == 429
                ) from exc
            raise ProviderFailure(
                "PROVIDER_SUBMISSION_UNCERTAIN", "The provider may have accepted this request", uncertain=True
            ) from exc
        finally:
            client.close()

    def cost(self, usage, snapshot):
        if usage.get("input_tokens") is None or usage.get("output_tokens") is None:
            return snapshot["reservation_micros"], "conservative_estimate"
        rate = snapshot["rate"]
        cost = math.ceil(
            (
                usage["input_tokens"] * rate["input_per_million_micros"]
                + usage["output_tokens"] * rate["output_per_million_micros"]
            )
            / 1_000_000
        )
        return cost, "usage_estimate"
