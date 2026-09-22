"""Veo video generation via Vertex AI."""

from __future__ import annotations

import os
import time
from pathlib import Path

from google import genai
from google.genai import types

from vibeshorts.config import VibeShortsConfig

VEO_MODEL = "veo-3.1-generate-001"


class VeoClient:
    def __init__(self, config: VibeShortsConfig):
        self.config = config
        self._client = genai.Client(
            vertexai=True,
            project=config.gcp.project or os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=config.gcp.location,
        )

    def generate_broll(
        self,
        prompt: str,
        output_gcs_uri: str,
        aspect_ratio: str = "9:16",
        duration_seconds: int = 6,
        reference_image_gcs: str | None = None,
    ) -> str:
        if not self.config.integrations.enable_veo:
            raise RuntimeError("Veo integration is disabled in config")

        ref_images = None
        if reference_image_gcs:
            ref_images = [
                types.VideoGenerationReferenceImage(
                    image=types.Image(gcs_uri=reference_image_gcs, mime_type="image/png"),
                    reference_type="asset",
                )
            ]

        operation = self._client.models.generate_videos(
            model=VEO_MODEL,
            prompt=prompt,
            config=types.GenerateVideosConfig(
                aspect_ratio=aspect_ratio,
                duration_seconds=duration_seconds,
                number_of_videos=1,
                output_gcs_uri=output_gcs_uri,
                reference_images=ref_images,
            ),
        )

        while not operation.done:
            time.sleep(5)
            operation = self._client.operations.get(operation)

        if not operation.response or not operation.response.generated_videos:
            raise RuntimeError("Veo generation failed or returned no videos")

        video = operation.response.generated_videos[0]
        return video.video.uri or output_gcs_uri

    def generate_local_placeholder(self, prompt: str, output_dir: Path) -> Path:
        """Fallback when Vertex/Veo credentials are unavailable."""
        output_dir.mkdir(parents=True, exist_ok=True)
        placeholder = output_dir / "broll_placeholder.txt"
        placeholder.write_text(f"Veo placeholder for prompt: {prompt}\n")
        return placeholder
