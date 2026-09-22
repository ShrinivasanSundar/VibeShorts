"""Gemini / Vertex AI client for video understanding and structured output."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from vibeshorts.config import VibeShortsConfig

T = TypeVar("T", bound=BaseModel)


class GeminiClient:
    def __init__(self, config: VibeShortsConfig, model: str | None = None):
        self.config = config
        self.model = model or config.antigravity.model
        self._client = genai.Client(
            vertexai=config.gcp.use_vertex,
            project=config.gcp.project or os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=config.gcp.location,
            api_key=None if config.gcp.use_vertex else os.environ.get("GOOGLE_API_KEY"),
        )

    def generate_text(self, prompt: str, system: str | None = None) -> str:
        contents = prompt
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.4,
        )
        response = self._client.models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )
        return response.text or ""

    def generate_structured(self, prompt: str, schema: type[T], system: str | None = None) -> T:
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.2,
        )
        response = self._client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
        text = response.text or "{}"
        return schema.model_validate_json(text)

    def analyze_video_file(self, video_path: Path, prompt: str) -> str:
        uploaded = self._client.files.upload(file=str(video_path))
        config = types.GenerateContentConfig(temperature=0.2)
        response = self._client.models.generate_content(
            model=self.model,
            contents=[prompt, uploaded],
            config=config,
        )
        return response.text or ""

    def refine_trim_probe(self, probe_path: Path, edge: str) -> dict:
        prompt = (
            f"Analyze this ~6 second video probe for the {edge} trim point. "
            "Return JSON with keys: refined_time (float seconds from probe start), "
            "confidence (0-1), reason (string). "
            "Snap to natural speech pause or visual cut boundary."
        )
        text = self.analyze_video_file(probe_path, prompt)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"refined_time": 0.0, "confidence": 0.0, "reason": text}
