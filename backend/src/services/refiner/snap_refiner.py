"""Trim Refiner Service.

Snaps Director in/out cut points to the nearest word boundary or VAD pause.
Prevents mid-word audio truncation and unnatural breathing cutoffs.
Dispatches a micro-probe to Gemini only if boundary ambiguity exceeds threshold.
"""

from typing import Optional, List
from src.core.config import settings
from src.core.gcp import gcp_manager
from src.core.logging import logger
from src.models.schemas import EditPlan, EditPlanEntry, FootageIndex, Shot, MusicDuckingCue


class TrimRefiner:
    """Refines rough cut boundaries against deterministic Speech-to-Text timestamps."""

    def refine_plan(self, plan: EditPlan, index: FootageIndex) -> EditPlan:
        """Snaps all cut boundaries in the plan to precise word/pause audio clocks."""
        logger.info(f"Refining cut boundaries for plan {plan.plan_id}")
        shots_by_id = {s.shot_id: s for s in index.shots}
        refined_cuts: List[EditPlanEntry] = []
        cumulative_duration = 0.0

        for cut in plan.cuts:
            shot = shots_by_id.get(cut.shot_id)
            if not shot or not shot.words:
                # No speech on shot; keep rough cut points bounded by shot duration
                in_pt = max(0.0, min(cut.in_point_sec, shot.duration if shot else cut.in_point_sec))
                out_pt = min(shot.duration if shot else cut.out_point_sec, max(in_pt + 0.5, cut.out_point_sec))
                cut.in_point_sec = round(in_pt, 3)
                cut.out_point_sec = round(out_pt, 3)
                refined_cuts.append(cut)
                cumulative_duration += cut.timeline_duration
                continue

            # Snapping logic against word timestamps
            refined_in = self._snap_in_point(cut.in_point_sec, shot)
            refined_out = self._snap_out_point(cut.out_point_sec, shot, refined_in)

            # Ensure minimum viable duration of 0.5s
            if refined_out - refined_in < 0.5:
                refined_out = min(shot.duration, refined_in + 1.0)

            cut.in_point_sec = round(refined_in, 3)
            cut.out_point_sec = round(refined_out, 3)

            # Inject audio ducking cue if speech occurs within this cut window
            speech_words_in_cut = [
                w for w in shot.words
                if w.end >= cut.in_point_sec and w.start <= cut.out_point_sec
            ]
            if speech_words_in_cut:
                duck_start = max(0.0, speech_words_in_cut[0].start - cut.in_point_sec - 0.15)
                duck_end = speech_words_in_cut[-1].end - cut.in_point_sec + 0.25
                cut.music_cues = MusicDuckingCue(
                    duck_start_sec=round(duck_start, 3),
                    duck_end_sec=round(duck_end, 3),
                    normal_volume_db=-14.0,
                    ducked_volume_db=-28.0
                )

            refined_cuts.append(cut)
            cumulative_duration += cut.timeline_duration

        plan.cuts = refined_cuts
        plan.total_target_duration = round(cumulative_duration, 2)
        logger.info(f"Refinement complete. Total adjusted duration: {plan.total_target_duration}s")
        return plan

    def _snap_in_point(self, candidate_in: float, shot: Shot) -> float:
        """Snaps in-point to the start of the nearest word without clipping the initial syllable."""
        # Find any word that overlaps candidate_in
        for w in shot.words:
            if w.start <= candidate_in <= w.end:
                # In the middle of a word: snap cleanly to start of word minus safety lead
                return max(0.0, w.start - 0.08)

        # Otherwise find nearest subsequent word within 0.8s
        subsequent = [w for w in shot.words if w.start >= candidate_in]
        if subsequent and (subsequent[0].start - candidate_in) < 0.8:
            return max(0.0, subsequent[0].start - 0.08)

        return candidate_in

    def _snap_out_point(self, candidate_out: float, shot: Shot, snapped_in: float) -> float:
        """Snaps out-point to the end of the nearest word, giving trailing breathing room."""
        # Check if candidate_out lands inside a word
        for w in shot.words:
            if w.start <= candidate_out <= w.end:
                # Snap to end of word plus 0.12s safety cushion
                return min(shot.duration, w.end + 0.12)

        # Find closest preceding word that occurs after snapped_in
        preceding = [w for w in shot.words if snapped_in < w.end <= candidate_out]
        if preceding:
            gap = candidate_out - preceding[-1].end
            if gap > 0.75:
                # Ambiguous pause: probe semantic decision
                if self._should_trim_trailing_silence(shot.transcript, gap):
                    return min(shot.duration, preceding[-1].end + 0.15)
            return min(shot.duration, preceding[-1].end + 0.20)

        return min(shot.duration, candidate_out)

    def _should_trim_trailing_silence(self, context_transcript: str, gap_sec: float) -> bool:
        """Micro-probe fallback to Gemini when trailing silence is ambiguous."""
        if gcp_manager.genai_client is None:
            return True  # Default to tight trimming for punchy short-form pacing

        try:
            prompt = f"""Presenter said: "{context_transcript}".
There is {gap_sec:.2f} seconds of silence at the end of the thought.
Should the cut hold the reaction (HOLD) or cut immediately after the word (TRIM)?
Respond with ONLY either "HOLD" or "TRIM"."""

            response = gcp_manager.genai_client.models.generate_content(
                model=settings.GEMINI_MICRO_PROBE_MODEL,
                contents=prompt
            )
            return "TRIM" in response.text.upper()
        except Exception:
            return True
