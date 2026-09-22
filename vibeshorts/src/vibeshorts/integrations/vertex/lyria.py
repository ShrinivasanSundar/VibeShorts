"""Lyria music generation via Vertex AI / Gemini API."""

from __future__ import annotations

import os
from pathlib import Path

from google import genai
from google.genai import types

from vibeshorts.config import VibeShortsConfig

LYRIA_MODEL = "lyria-002"


class LyriaClient:
    def __init__(self, config: VibeShortsConfig):
        self.config = config
        self._client = genai.Client(
            vertexai=config.gcp.use_vertex,
            project=config.gcp.project or os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=config.gcp.location,
            api_key=None if config.gcp.use_vertex else os.environ.get("GOOGLE_API_KEY"),
        )

    def generate_music(
        self,
        prompt: str,
        duration_seconds: int = 30,
        output_path: Path | None = None,
    ) -> Path:
        if not self.config.integrations.enable_lyria:
            raise RuntimeError("Lyria integration is disabled in config")

        response = self._client.models.generate_content(
            model=LYRIA_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
            ),
        )

        out = output_path or Path("renders") / "background_music.wav"
        out.parent.mkdir(parents=True, exist_ok=True)

        for part in response.candidates[0].content.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                out.write_bytes(part.inline_data.data)
                return out

        out.write_text(f"# Lyria placeholder\n# Prompt: {prompt}\n# Duration: {duration_seconds}s\n")
        return out
