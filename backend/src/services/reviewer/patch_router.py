"""Patch Router.

Enforces bifurcated self-healing:
1. Story patches route back to the Director (capped at MAX_REVIEW_RETRIES).
2. Render/Caption/Loudness patches route directly to the FFmpeg Editor (bypassing LLM re-planning).
3. If no patches remain or cap is hit, marks the export as finalized.
"""

from typing import List, Tuple
from src.core.config import settings
from src.core.logging import logger
from src.models.schemas import ReviewPatch


class PatchRouter:
    """Evaluates patches and determines next pipeline action."""

    def route_patches(
        self,
        patches: List[ReviewPatch],
        current_revision: int
    ) -> Tuple[bool, str, List[ReviewPatch]]:
        """Returns (is_terminal, next_actor, filtered_patches).

        next_actor can be 'director', 'editor', or 'complete'.
        """
        if not patches:
            logger.info("Zero review patches returned. Edit successfully finalized.")
            return True, "complete", []

        if current_revision >= settings.MAX_REVIEW_RETRIES:
            logger.info(f"Max retries reached ({current_revision}/{settings.MAX_REVIEW_RETRIES}). Forcing completion.")
            return True, "complete", []

        # Check for story patches
        story_patches = [p for p in patches if p.target_entity == "director"]
        if story_patches:
            logger.info(f"Routing {len(story_patches)} story patches to Director (revision {current_revision + 1})")
            return False, "director", story_patches

        # Otherwise only editor-level patches remain
        editor_patches = [p for p in patches if p.target_entity == "editor"]
        logger.info(f"Routing {len(editor_patches)} render patches directly to FFmpeg Editor (bypassing Director)")
        return False, "editor", editor_patches
