"""Master Workflow Orchestrator.

Executes the autonomous loop:
Ingest -> Director -> Refiner -> Editor (Render) -> Reviewer -> (Self-Healing Loop) -> Final Export.
"""

from pathlib import Path
from typing import Callable, List, Optional
from src.core.config import settings
from src.core.logging import logger
from src.models.schemas import (
    CreativeBrief,
    FootageIndex,
    EditPlan,
    PipelineStage,
    JobStatus
)
from src.services.ingest.pipeline import IngestPipeline
from src.services.director.agent import DirectorAgent
from src.services.refiner.snap_refiner import TrimRefiner
from src.services.editor.ffmpeg_builder import FFmpegEditor
from src.services.reviewer.agent import ReviewerAgent
from src.services.reviewer.patch_router import PatchRouter


class VideoOrchestrator:
    """Coordinates the entire multi-agent video production lifecycle."""

    def __init__(self):
        self.ingest_pipeline = IngestPipeline()
        self.director_agent = DirectorAgent()
        self.trim_refiner = TrimRefiner()
        self.ffmpeg_editor = FFmpegEditor()
        self.reviewer_agent = ReviewerAgent()
        self.patch_router = PatchRouter()

    def run_pipeline(
        self,
        job_id: str,
        project_id: str,
        media_paths: List[Path],
        brief: CreativeBrief,
        progress_callback: Optional[Callable[[JobStatus], None]] = None
    ) -> JobStatus:
        """Executes the full pipeline until convergence or retry limit."""
        status = JobStatus(
            job_id=job_id,
            project_id=project_id,
            stage=PipelineStage.INGESTING,
            progress_percentage=10,
            message="Starting deterministic ingest..."
        )
        if progress_callback:
            progress_callback(status)

        try:
            # 1. Deterministic Ingest
            footage_index: FootageIndex = self.ingest_pipeline.process_project_footage(project_id, media_paths)
            status.stage = PipelineStage.INDEXED
            status.progress_percentage = 30
            status.message = f"Footage indexed: {len(footage_index.shots)} shots identified."
            if progress_callback:
                progress_callback(status)

            # Revision loop variables
            revision = 1
            patches = None
            current_plan = None
            final_mp4 = settings.OUTPUT_DIR / f"{project_id}_final.mp4"

            while True:
                # 2. Director Agent
                status.stage = PipelineStage.DIRECTING
                status.progress_percentage = min(40 + (revision * 5), 55)
                status.message = f"Director Agent synthesizing EditPlan (revision {revision})..."
                if progress_callback:
                    progress_callback(status)

                rough_plan: EditPlan = self.director_agent.plan_edit(
                    brief=brief,
                    index=footage_index,
                    revisions=revision,
                    patches=patches,
                    previous_plan=current_plan
                )

                # 3. Trim Refiner (Audio Clocks)
                status.stage = PipelineStage.REFINING
                status.progress_percentage = 60
                status.message = "Snapping cut boundaries to nearest word and pause timestamps..."
                if progress_callback:
                    progress_callback(status)

                current_plan = self.trim_refiner.refine_plan(rough_plan, footage_index)
                status.edit_plan = current_plan

                # 4. FFmpeg Editor (Execution)
                status.stage = PipelineStage.RENDERING
                status.progress_percentage = 75
                status.message = "FFmpeg cutting, reframing 9:16, burning ASS captions..."
                if progress_callback:
                    progress_callback(status)

                rendered_cut = settings.TEMP_DIR / f"{project_id}_rev{revision}.mp4"
                self.ffmpeg_editor.render_edit_plan(current_plan, footage_index, rendered_cut)

                # 5. Reviewer Agent
                status.stage = PipelineStage.REVIEWING
                status.progress_percentage = 85
                status.message = "Reviewer Agent inspecting rendered MP4 for defects..."
                if progress_callback:
                    progress_callback(status)

                patches = self.reviewer_agent.review_rendered_video(rendered_cut, current_plan, revision)

                # 6. Patch Router
                is_terminal, next_actor, filtered_patches = self.patch_router.route_patches(patches, revision)

                if is_terminal or next_actor == "complete":
                    # Copy to final destination
                    import shutil
                    shutil.copyfile(rendered_cut, final_mp4)
                    break
                elif next_actor == "director":
                    revision += 1
                    patches = filtered_patches
                    status.stage = PipelineStage.PATCHING
                    status.message = f"Story patch applied: re-routing to Director (revision {revision})"
                    if progress_callback:
                        progress_callback(status)
                elif next_actor == "editor":
                    # Re-render directly
                    revision += 1
                    status.stage = PipelineStage.RENDERING
                    status.message = "Re-rendering directly with Editor patches..."
                    if progress_callback:
                        progress_callback(status)
                    self.ffmpeg_editor.render_edit_plan(current_plan, footage_index, final_mp4)
                    break

            status.stage = PipelineStage.COMPLETED
            status.progress_percentage = 100
            status.output_video_uri = str(final_mp4.resolve())
            status.message = "Video edit finalized and ready for export."
            if progress_callback:
                progress_callback(status)

            return status

        except Exception as e:
            logger.error(f"Pipeline failure on job {job_id}: {e}", exc_info=True)
            status.stage = PipelineStage.FAILED
            status.error = str(e)
            status.message = f"Pipeline execution failed: {e}"
            if progress_callback:
                progress_callback(status)
            return status
