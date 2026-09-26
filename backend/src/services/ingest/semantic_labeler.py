"""Gemini Semantic Labeler.

Labels shot visual content and classifies roll_type (A-roll talking head vs B-roll cutaway).
Architectural Enforcement: Gemini is NEVER asked or permitted to output cut timestamps.
"""

from pathlib import Path
from typing import Tuple
from src.core.config import settings
from src.core.gcp import gcp_manager
from src.core.logging import logger
from src.models.schemas import RollType


class SemanticLabeler:
    """Labels visual content and roll type using Gemini 1.5 Flash."""

    def label_shot(
        self,
        keyframe_path: Path,
        transcript: str,
        has_speech: bool
    ) -> Tuple[RollType, str]:
        """Classifies shot roll_type and generates a concise visual description.

        Returns (RollType, semantic_description).
        """
        if gcp_manager.genai_client is not None and keyframe_path.exists():
            try:
                return self._label_with_gemini(keyframe_path, transcript, has_speech)
            except Exception as e:
                logger.error(f"Gemini labeling failed ({e}); falling back to heuristic labeling")

        return self._heuristic_label(transcript, has_speech)

    def _label_with_gemini(
        self,
        keyframe_path: Path,
        transcript: str,
        has_speech: bool
    ) -> Tuple[RollType, str]:
        """Calls Gemini Flash via google.genai with structured JSON response."""
        from google import genai
        from google.genai import types

        with open(keyframe_path, "rb") as f:
            image_bytes = f.read()

        prompt = f"""You are a video ingest assistant. Analyze this video keyframe and transcript.
Do NOT emit any timestamps or timecodes under any circumstances.

Transcript: "{transcript}"
Has Detected Speech: {has_speech}

Classify:
1. roll_type: "a_roll" if this is a primary speaker / talking head addressing the camera; otherwise "b_roll" (product demonstration, scenery, contextual action).
2. description: A concise 1-2 sentence description of what is shown visually.

Format your response as valid JSON:
{{"roll_type": "a_roll" | "b_roll", "description": "<concise description>"}}
"""

        response = gcp_manager.genai_client.models.generate_content(
            model=settings.GEMINI_LABELER_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                prompt
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            )
        )

        import json
        data = json.loads(response.text)
        roll = RollType.A_ROLL if data.get("roll_type") == "a_roll" else RollType.B_ROLL
        desc = data.get("description", "Video shot")
        return roll, desc

    def _heuristic_label(self, transcript: str, has_speech: bool) -> Tuple[RollType, str]:
        """Deterministic heuristic fallback when running in local/test mode."""
        if has_speech and len(transcript.split()) >= 3:
            return RollType.A_ROLL, f"Presenter speaking: {transcript[:60]}..."
        return RollType.B_ROLL, "Visual B-roll clip / product presentation"
