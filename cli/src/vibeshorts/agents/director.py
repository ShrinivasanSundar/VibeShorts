"""Director agent — searches footage and produces EditPlan."""

from __future__ import annotations

from pathlib import Path

from vibeshorts.config import VibeShortsConfig
from vibeshorts.integrations.vertex.gemini import GeminiClient
from vibeshorts.models.schemas import CreativeBrief, EditPlan, FootageIndex

DIRECTOR_SYSTEM = """You are the VibeShorts Director. Given a creative brief and footage index,
produce a structured EditPlan for a short-form vertical video (9:16).

Rules:
- Hook in first 3 seconds
- Alternate A-roll and B-roll for pacing
- Respect target duration
- Use shot_id format: {source_file}#{start_time}
- Include text_overlay for key moments when appropriate
"""


class DirectorAgent:
    def __init__(self, config: VibeShortsConfig):
        self.gemini = GeminiClient(config)

    def create_plan(
        self,
        brief: CreativeBrief,
        index: FootageIndex,
        style_yaml: Path | None = None,
        feedback: str | None = None,
    ) -> EditPlan:
        style_context = ""
        if style_yaml and style_yaml.exists():
            style_context = f"\nStyle template:\n{style_yaml.read_text()}"

        feedback_context = f"\nReviewer feedback to address:\n{feedback}" if feedback else ""

        shots_summary = [
            {
                "id": s.id,
                "source": s.source_file,
                "start": s.start_time,
                "end": s.end_time,
                "roll_type": s.roll_type,
                "transcript": s.transcript[:200],
            }
            for s in index.shots[:50]
        ]

        prompt = f"""{DIRECTOR_SYSTEM}

Creative Brief:
{brief.model_dump_json(indent=2)}

Available shots (sample):
{shots_summary}
{style_context}
{feedback_context}

Return a complete EditPlan JSON.
"""
        return self.gemini.generate_structured(prompt, EditPlan, system=DIRECTOR_SYSTEM)
