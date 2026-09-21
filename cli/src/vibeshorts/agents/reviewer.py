"""Reviewer agent — multimodal QA scoring."""

from __future__ import annotations

import asyncio
from pathlib import Path

from vibeshorts.config import VibeShortsConfig
from vibeshorts.integrations.antigravity import ShowrunnerAgent
from vibeshorts.integrations.vertex.gemini import GeminiClient
from vibeshorts.models.schemas import CreativeBrief, ReviewScore

REVIEWER_SYSTEM = """You are the VibeShorts Reviewer. Watch the rendered short-form video and score it.

Score each dimension from 0.0 to 1.0:
- adherence: matches product, audience, tone
- pacing: hook strength, cut rhythm, energy
- visual_quality: framing, readability, captions
- watchability: retention likelihood

Provide specific, timestamped critique when score is below 0.7.
"""


class ReviewerAgent:
    def __init__(self, config: VibeShortsConfig, project_dir: Path):
        self.config = config
        self.project_dir = project_dir
        self.gemini = GeminiClient(config)
        self.showrunner = ShowrunnerAgent(config, project_dir)

    def review(self, brief: CreativeBrief, video_path: Path, threshold: float) -> ReviewScore:
        prompt = f"""{REVIEWER_SYSTEM}

Brief: {brief.model_dump_json()}
Pass threshold: {threshold}

Analyze the video and return ReviewScore JSON.
"""
        try:
            score = self.gemini.generate_structured(prompt, ReviewScore, system=REVIEWER_SYSTEM)
        except Exception:
            score = ReviewScore(
                adherence=0.5,
                pacing=0.5,
                visual_quality=0.5,
                watchability=0.5,
                overall=0.5,
                critique="Reviewer fallback — enable video upload for full QA.",
            )

        score.compute_overall()
        score.passed = score.overall >= threshold
        return score

    async def review_async(
        self,
        brief: CreativeBrief,
        video_path: Path,
        threshold: float,
    ) -> ReviewScore:
        try:
            return await self.showrunner.review_render(brief, video_path, threshold)
        except Exception:
            return self.review(brief, video_path, threshold)

    def review_sync(self, brief: CreativeBrief, video_path: Path, threshold: float) -> ReviewScore:
        return asyncio.run(self.review_async(brief, video_path, threshold))
