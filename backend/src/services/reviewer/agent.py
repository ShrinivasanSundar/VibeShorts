"""Reviewer Agent.

Watches the rendered MP4 with Gemini 1.5 Pro and produces structured ReviewPatch items.
Enforces that review is an actionable patch list rather than an arbitrary numeric score.
"""

import json
from pathlib import Path
from typing import List
from src.core.config import settings
from src.core.gcp import gcp_manager
from src.core.logging import logger
from src.models.schemas import EditPlan, ReviewPatch, PatchType


class ReviewerAgent:
    """Multimodal QA Reviewer inspecting the final cut against viral standards."""

    def review_rendered_video(
        self,
        video_path: Path,
        plan: EditPlan,
        revision: int
    ) -> List[ReviewPatch]:
        """Analyzes rendered MP4 and returns a targeted list of patches."""
        logger.info(f"Reviewer evaluating video {video_path.name} (revision {revision})")

        # If revision cap reached, emit zero patches to force termination
        if revision >= settings.MAX_REVIEW_RETRIES:
            logger.info(f"Revision count {revision} reached MAX_REVIEW_RETRIES ({settings.MAX_REVIEW_RETRIES}). Finalizing.")
            return []

        if gcp_manager.genai_client is not None and video_path.exists():
            try:
                return self._review_with_gemini(video_path, plan)
            except Exception as e:
                logger.error(f"Gemini Reviewer call failed ({e}); falling back to heuristic review")

        return self._heuristic_review(plan)

    def _review_with_gemini(self, video_path: Path, plan: EditPlan) -> List[ReviewPatch]:
        """Uploads video to Vertex AI / Gemini and receives structured patch instructions."""
        from google.genai import types

        video_file = gcp_manager.genai_client.files.upload(file=str(video_path))

        prompt = """You are a master short-form video editor reviewing a TikTok/Reels edit.
Watch the video closely and identify any critical defects.

Critique criteria:
1. Hook Pacing: Does cut #1 grab attention immediately? Should it be trimmed or swapped?
2. Cut Boredom: Is any cut holding static for > 4.5 seconds?
3. Reframing: Is a person's face or product cut off outside the 9:16 frame?
4. Caption Drift: Are words misaligned with the spoken audio?
5. Loudness / Audio: Is speech buried under background sound?

Categorize each defect strictly into:
- target_entity: "director" for story, shot choice, or hook tightening.
- target_entity: "editor" for caption timing, crop re-centering, or loudness adjustments.

Format output as valid JSON:
{
  "patches": [
    {
      "patch_type": "tighten_hook" | "swap_shot" | "reframe_crop" | "fix_caption_drift" | "adjust_loudness",
      "target_cut_index": int,
      "target_entity": "director" | "editor",
      "rationale": "...",
      "suggested_action": "..."
    }
  ]
}
If the video is satisfactory and ready to publish, return {"patches": []}.
"""

        response = gcp_manager.genai_client.models.generate_content(
            model=settings.GEMINI_REVIEWER_MODEL,
            contents=[video_file, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            )
        )

        data = json.loads(response.text)
        patches: List[ReviewPatch] = []
        for p in data.get("patches", []):
            try:
                patches.append(ReviewPatch(**p))
            except Exception as parse_err:
                logger.warning(f"Error parsing patch {p}: {parse_err}")

        return patches

    def _heuristic_review(self, plan: EditPlan) -> List[ReviewPatch]:
        """Deterministic heuristic review for testing and offline environments."""
        patches: List[ReviewPatch] = []

        # Heuristic 1: If first cut is longer than 3.5s, request hook tightening
        if plan.cuts and plan.cuts[0].timeline_duration > 3.5:
            patches.append(ReviewPatch(
                patch_type=PatchType.TIGHTEN_HOOK,
                target_cut_index=1,
                target_entity="director",
                rationale="Opening cut exceeds 3.5s; tighten hook to improve 3s retention rate.",
                suggested_action="Shorten cut #1 duration by 1.0s or pick a punchier clip."
            ))

        return patches
