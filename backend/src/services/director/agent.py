"""Director Agent.

Uses Gemini (via AntiGravity SDK / Google GenAI) to synthesize a narrative EditPlan
from a CreativeBrief and the FootageIndex.
The Director defines story order and pacing; cut clocks come strictly from the index.
"""

import json
from typing import List, Optional
from src.core.config import settings
from src.core.gcp import gcp_manager
from src.core.logging import logger
from src.models.schemas import (
    CreativeBrief,
    FootageIndex,
    EditPlan,
    EditPlanEntry,
    ReviewPatch,
    RollType,
    BoundingBox
)


class DirectorAgent:
    """Creative Director Agent orchestrating storytelling and visual progression."""

    def plan_edit(
        self,
        brief: CreativeBrief,
        index: FootageIndex,
        revisions: int = 1,
        patches: Optional[List[ReviewPatch]] = None,
        previous_plan: Optional[EditPlan] = None
    ) -> EditPlan:
        """Generates or revises an EditPlan matching the creative brief."""
        logger.info(f"Director planning edit for project={index.project_id}, revision={revisions}")

        if gcp_manager.genai_client is not None:
            try:
                return self._plan_with_gemini(brief, index, revisions, patches, previous_plan)
            except Exception as e:
                logger.error(f"Gemini Director call failed ({e}); falling back to heuristic planner")

        return self._heuristic_planner(brief, index, revisions)

    def _plan_with_gemini(
        self,
        brief: CreativeBrief,
        index: FootageIndex,
        revisions: int,
        patches: Optional[List[ReviewPatch]],
        previous_plan: Optional[EditPlan]
    ) -> EditPlan:
        """Executes LLM creative planning with structured schema enforcement."""
        from google.genai import types

        # Build compact shot catalog for prompt
        catalog_summary = []
        for s in index.shots:
            catalog_summary.append({
                "shot_id": s.shot_id,
                "roll_type": s.roll_type.value,
                "duration": s.duration,
                "has_speech": s.has_speech,
                "description": s.semantic_description,
                "transcript": s.transcript
            })

        system_instruction = """You are an expert Hollywood and viral short-form video director.
Your objective is to create an EditPlan for a 9:16 short-form video (TikTok/Reels/Shorts).
Rule 1: Hook the viewer in the first 1-3 seconds with a high-impact hook or punchy question.
Rule 2: Balance A-roll (narrator/talking head) with frequent B-roll cutaways every 2-4 seconds.
Rule 3: Only use shots that exist in the provided Shot Catalog. Do NOT invent new shot_ids.
Rule 4: Select in_point_sec and out_point_sec within the bounds [0.0, shot.duration].
Rule 5: Keep the cumulative duration close to target duration.
"""

        patch_instruction = ""
        if patches:
            patch_instruction = f"Address these specific review critique patches: {json.dumps([p.model_dump() for p in patches])}"

        user_instruction_block = f"- User Specific Direction: {brief.user_prompt}\n" if brief.user_prompt else ""

        prompt = f"""
Creative Brief:
- Product: {brief.product_name}
- Audience: {brief.target_audience}
- Tone: {brief.tone}
- Target Duration: {brief.duration_seconds}s
- Key Value Props: {brief.key_value_props}
- CTA: {brief.call_to_action}
{user_instruction_block}
Available Shot Catalog:
{json.dumps(catalog_summary, indent=2)}

{patch_instruction}

Output a JSON object with:
- plan_id: "plan_{index.project_id}_v{revisions}"
- cuts: list of entries, each with:
    - cut_index: int (1-based)
    - shot_id: string (must match catalog)
    - in_point_sec: float
    - out_point_sec: float
    - text_overlay: optional short text punchline
"""

        response = gcp_manager.genai_client.models.generate_content(
            model=settings.GEMINI_DIRECTOR_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                temperature=0.4
            )
        )

        plan_data = json.loads(response.text)
        shots_by_id = {s.shot_id: s for s in index.shots}
        entries: List[EditPlanEntry] = []
        total_time = 0.0

        for c in plan_data.get("cuts", []):
            sid = c["shot_id"]
            if sid not in shots_by_id:
                continue
            shot = shots_by_id[sid]
            in_pt = max(0.0, float(c.get("in_point_sec", 0.0)))
            out_pt = min(shot.duration, float(c.get("out_point_sec", shot.duration)))
            if out_pt <= in_pt:
                out_pt = min(shot.duration, in_pt + 2.0)

            crop_box = shot.primary_focus_box or BoundingBox(ymin=0.0, xmin=0.21875, ymax=1.0, xmax=0.78125)

            entry = EditPlanEntry(
                cut_index=len(entries) + 1,
                shot_id=sid,
                source_file_uri=shot.source_file_uri,
                in_point_sec=round(in_pt, 3),
                out_point_sec=round(out_pt, 3),
                crop_9_16=crop_box,
                text_overlay=c.get("text_overlay")
            )
            entries.append(entry)
            total_time += entry.timeline_duration

        return EditPlan(
            plan_id=f"plan_{index.project_id}_v{revisions}",
            project_id=index.project_id,
            revision=revisions,
            total_target_duration=round(total_time, 2),
            cuts=entries
        )

    def _heuristic_planner(self, brief: CreativeBrief, index: FootageIndex, revisions: int) -> EditPlan:
        """Deterministic algorithmic planner ensuring valid story progression."""
        a_rolls = [s for s in index.shots if s.roll_type == RollType.A_ROLL]
        b_rolls = [s for s in index.shots if s.roll_type != RollType.A_ROLL]

        selected_shots = []
        target_dur = float(brief.duration_seconds)
        current_dur = 0.0

        # Alternate A-roll and B-roll
        idx_a, idx_b = 0, 0
        while current_dur < target_dur and (idx_a < len(a_rolls) or idx_b < len(b_rolls)):
            if idx_a < len(a_rolls):
                selected_shots.append(a_rolls[idx_a])
                current_dur += a_rolls[idx_a].duration
                idx_a += 1
            if current_dur >= target_dur:
                break
            if idx_b < len(b_rolls):
                selected_shots.append(b_rolls[idx_b])
                current_dur += b_rolls[idx_b].duration
                idx_b += 1

        if not selected_shots:
            selected_shots = index.shots

        entries: List[EditPlanEntry] = []
        accumulated_dur = 0.0

        for i, s in enumerate(selected_shots):
            rem = target_dur - accumulated_dur
            if rem <= 0.5:
                break
            dur = min(s.duration, rem, 4.5)
            crop_box = s.primary_focus_box or BoundingBox(ymin=0.0, xmin=0.21875, ymax=1.0, xmax=0.78125)

            entries.append(EditPlanEntry(
                cut_index=i + 1,
                shot_id=s.shot_id,
                source_file_uri=s.source_file_uri,
                in_point_sec=0.0,
                out_point_sec=round(dur, 3),
                crop_9_16=crop_box,
                text_overlay=brief.key_value_props[i] if i < len(brief.key_value_props) else None
            ))
            accumulated_dur += dur

        return EditPlan(
            plan_id=f"plan_{index.project_id}_v{revisions}",
            project_id=index.project_id,
            revision=revisions,
            total_target_duration=round(accumulated_dur, 2),
            cuts=entries
        )
