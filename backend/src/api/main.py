"""FastAPI Application Entrypoint for VibeShorts Backend.

Provides endpoints for media upload, job dispatch, SSE progress streaming, and video retrieval.
"""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Dict, List
from fastapi import FastAPI, File, UploadFile, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

from src.core.config import settings
from src.core.logging import logger
from src.core.gcp import gcp_manager
from src.models.schemas import (
    CreativeBrief,
    JobStatus,
    PipelineStage,
    EditPlan,
    EditPlanEntry,
    FootageIndex,
    ChatRequest,
    ChatResponse
)
from src.services.orchestrator import VideoOrchestrator


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Autonomous AI Video Production Engine powered by Google Cloud & Gemini"
)

# CORS setup for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = VideoOrchestrator()

# In-memory job repository (can be swapped with Redis / Cloud SQL in production)
job_store: Dict[str, JobStatus] = {}
job_event_queues: Dict[str, asyncio.Queue] = {}


class TriggerEditRequest(BaseModel):
    brief: CreativeBrief


@app.get("/health")
def healthcheck():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT
    }


@app.post(f"{settings.API_V1_PREFIX}/projects/{{project_id}}/upload")
async def upload_footage(project_id: str, files: List[UploadFile] = File(...)):
    """Uploads raw video footage for a project."""
    project_dir = settings.STORAGE_DIR / "uploads" / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []
    for file in files:
        target_path = project_dir / file.filename
        with open(target_path, "wb") as f:
            content = await file.read()
            f.write(content)
        saved_files.append(str(target_path.resolve()))

    return {
        "project_id": project_id,
        "uploaded_count": len(saved_files),
        "files": saved_files
    }


def _run_pipeline_background(job_id: str, project_id: str, media_paths: List[Path], brief: CreativeBrief):
    """Background task executor broadcasting status updates."""
    def progress_callback(status: JobStatus):
        job_store[job_id] = status
        if job_id in job_event_queues:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.call_soon_threadsafe(job_event_queues[job_id].put_nowait, status)
            except Exception:
                pass

    orchestrator.run_pipeline(
        job_id=job_id,
        project_id=project_id,
        media_paths=media_paths,
        brief=brief,
        progress_callback=progress_callback
    )


@app.post(f"{settings.API_V1_PREFIX}/projects/{{project_id}}/generate")
async def trigger_generation(
    project_id: str,
    payload: TriggerEditRequest,
    background_tasks: BackgroundTasks
):
    """Starts autonomous video generation pipeline."""
    project_dir = settings.STORAGE_DIR / "uploads" / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=400, detail="No footage uploaded for this project.")

    media_paths = list(project_dir.glob("*.mp4")) + list(project_dir.glob("*.mov"))
    if not media_paths:
        raise HTTPException(status_code=400, detail="No valid MP4/MOV footage found.")

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    initial_status = JobStatus(
        job_id=job_id,
        project_id=project_id,
        stage=PipelineStage.INGESTING,
        progress_percentage=0,
        message="Job queued for execution."
    )
    job_store[job_id] = initial_status
    job_event_queues[job_id] = asyncio.Queue()

    background_tasks.add_task(
        _run_pipeline_background,
        job_id=job_id,
        project_id=project_id,
        media_paths=media_paths,
        brief=payload.brief
    )

    return {"job_id": job_id, "status": initial_status}


@app.get(f"{settings.API_V1_PREFIX}/jobs/{{job_id}}/status")
def get_job_status(job_id: str):
    """Retrieves current job status."""
    if job_id not in job_store:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_store[job_id]


@app.get(f"{settings.API_V1_PREFIX}/jobs/{{job_id}}/stream")
async def stream_job_events(job_id: str):
    """Server-Sent Events (SSE) endpoint for real-time progress updates to frontend."""
    if job_id not in job_store:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        # Yield current status immediately
        yield f"data: {job_store[job_id].model_dump_json()}\n\n"

        queue = job_event_queues.get(job_id)
        while True:
            if not queue:
                break
            status: JobStatus = await queue.get()
            yield f"data: {status.model_dump_json()}\n\n"
            if status.stage in (PipelineStage.COMPLETED, PipelineStage.FAILED):
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get(f"{settings.API_V1_PREFIX}/videos/{{filename}}")
def get_rendered_video(filename: str):
    """Serves the rendered MP4 video file."""
    video_path = settings.OUTPUT_DIR / filename
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found")
    return FileResponse(video_path, media_type="video/mp4")


@app.post(f"{settings.API_V1_PREFIX}/projects/{{project_id}}/chat", response_model=ChatResponse)
async def chat_with_director(project_id: str, payload: ChatRequest):
    """Conversational endpoint for the Creative Director & Editor Agent.
    Interprets natural language editing instructions (trim, swap, captions, pacing) and updates the EditPlan.
    """
    user_msg = payload.message.strip()
    plan = payload.edit_plan
    brief = payload.brief
    
    suggested_prompts = [
        "⚡ Generate 30s High-Energy Reel",
        "✂️ Tighten Hook to First 3 Seconds",
        "🎵 Switch to Synthwave Beat"
    ]
    
    # If Gemini is configured, use it for intelligent conversation and plan updates
    if gcp_manager.genai_client is not None:
        try:
            from google.genai import types
            prompt = f"""You are the AI Creative Director & Editor of VibeShorts, a 9:16 short-form video engine.
User Message: "{user_msg}"
Current Brief: {brief.model_dump_json() if brief else 'None'}
Current Edit Plan: {plan.model_dump_json() if plan else 'None'}

Analyze the user's intent. If they are asking for changes or feedback, respond concisely in director style.
If they request timeline modifications (e.g. trim, change captions, swap shots, reorder), output an updated EditPlan cuts or brief if applicable.

Output a JSON object with:
- "message": string (conversational response)
- "action": string or null (e.g. "plan_updated", "brief_updated", "re-render_ready", "advice")
- "updated_cuts": list or null (same schema as EditPlan cuts if modified)
- "suggested_prompts": list of 3 short follow-up suggestions
"""
            res = gcp_manager.genai_client.models.generate_content(
                model=settings.GEMINI_DIRECTOR_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.3
                )
            )
            parsed = json.loads(res.text)
            resp_msg = parsed.get("message", "I've reviewed your request.")
            resp_action = parsed.get("action")
            prompts = parsed.get("suggested_prompts", suggested_prompts)
            
            updated_plan = plan
            if parsed.get("updated_cuts") and plan:
                updated_plan = plan.model_copy(deep=True)
                updated_plan.cuts = [EditPlanEntry(**c) for c in parsed["updated_cuts"]]
                updated_plan.revision += 1
                
            return ChatResponse(
                message=resp_msg,
                action=resp_action,
                suggested_plan=updated_plan,
                suggested_brief=brief,
                suggested_prompts=prompts
            )
        except Exception as e:
            logger.warning(f"Gemini conversational call failed: {e}")

    # Deterministic fallback logic for conversational editing
    lower = user_msg.lower()
    updated_plan = plan.model_copy(deep=True) if plan else None
    resp_msg = ""
    resp_action = "advice"
    
    # 1. Trimming or shortening hooks
    if "trim" in lower or "shorten" in lower or "hook" in lower:
        if updated_plan and updated_plan.cuts:
            cut0 = updated_plan.cuts[0]
            old_dur = cut0.out_point_sec - cut0.in_point_sec
            new_dur = max(1.5, old_dur * 0.75)
            cut0.out_point_sec = round(cut0.in_point_sec + new_dur, 2)
            updated_plan.revision += 1
            updated_plan.total_target_duration = round(sum(c.timeline_duration for c in updated_plan.cuts), 2)
            resp_msg = f"⚡ Trimmed Cut #1 hook to {new_dur:.1f}s for maximum viral retention. Ready to re-render!"
            resp_action = "plan_updated"
        else:
            resp_msg = "I can trim the hook once footage is uploaded and the initial plan is generated!"
            
    # 2. Captions / text overlay updates
    elif "caption" in lower or "text" in lower or "subtitle" in lower:
        if updated_plan and updated_plan.cuts:
            import re
            quotes = re.findall(r"['\"](.*?)['\"]", user_msg)
            new_text = quotes[0] if quotes else "Game Changer"
            updated_plan.cuts[0].text_overlay = new_text
            updated_plan.revision += 1
            resp_msg = f"✍️ Updated hook caption overlay to \"{new_text}\". Burned in safe region."
            resp_action = "plan_updated"
        else:
            resp_msg = "Captions will be aligned to speech and dynamic ASS styles automatically."

    # 3. Swap or reorder shots
    elif "swap" in lower or "switch" in lower or "reverse" in lower:
        if updated_plan and len(updated_plan.cuts) >= 2:
            updated_plan.cuts[0], updated_plan.cuts[1] = updated_plan.cuts[1], updated_plan.cuts[0]
            updated_plan.cuts[0].cut_index = 1
            updated_plan.cuts[1].cut_index = 2
            updated_plan.revision += 1
            resp_msg = "🔄 Swapped Cut #1 and Cut #2 to lead with a high-energy B-roll teaser."
            resp_action = "plan_updated"
        else:
            resp_msg = "You can swap any shots on the timeline or ask me to rearrange them."

    # 4. Tone / Pacing adjustments
    elif any(t in lower for t in ["energetic", "dramatic", "educational", "humorous", "minimalist"]):
        matched_tone = next((t for t in ["energetic", "dramatic", "educational", "humorous", "minimalist"] if t in lower), "energetic")
        if brief:
            brief = brief.model_copy()
            brief.tone = matched_tone
        resp_msg = f"🎭 Shifted creative pacing to **{matched_tone.upper()}**. Cut lengths and transitions will adapt."
        resp_action = "brief_updated"

    # 5. Direct Render Request
    elif "render" in lower or "generate" in lower or "export" in lower:
        resp_msg = "🎬 Triggering FFmpeg 9:16 re-render pass with updated timeline specifications."
        resp_action = "re-render_ready"

    else:
        resp_msg = (
            "I'm ready to direct your cut! You can ask me to **trim the hook**, **rewrite subtitles**, "
            "**swap shots**, **adjust pacing**, or click on the interactive timeline to edit cuts manually."
        )

    return ChatResponse(
        message=resp_msg,
        action=resp_action,
        suggested_plan=updated_plan,
        suggested_brief=brief,
        suggested_prompts=[
            "✂️ Trim first cut by 1s",
            "✨ Add punchy caption: 'Must Have'",
            "🚀 Re-render final video"
        ]
    )


class RenderPlanPayload(BaseModel):
    plan: EditPlan


@app.post(f"{settings.API_V1_PREFIX}/projects/{{project_id}}/render-plan")
def render_custom_plan(project_id: str, payload: RenderPlanPayload):
    """Renders an edited or modified EditPlan directly with FFmpeg."""
    project_dir = settings.STORAGE_DIR / "uploads" / project_id
    media_paths = list(project_dir.glob("*.mp4")) + list(project_dir.glob("*.mov")) if project_dir.exists() else []
    
    footage_index = orchestrator.ingest_pipeline.process_project_footage(project_id, media_paths) if media_paths else FootageIndex(project_id=project_id)
    
    final_mp4 = settings.OUTPUT_DIR / f"{project_id}_final.mp4"
    orchestrator.ffmpeg_editor.render_edit_plan(payload.plan, footage_index, final_mp4)
    
    return {
        "status": "completed",
        "video_url": f"/api/v1/videos/{project_id}_final.mp4",
        "plan": payload.plan
    }


@app.get(f"{settings.API_V1_PREFIX}/projects/{{project_id}}/catalog")
def get_project_catalog(project_id: str):
    """Returns list of uploaded media files and indexed shots."""
    project_dir = settings.STORAGE_DIR / "uploads" / project_id
    if not project_dir.exists():
        return {"files": [], "count": 0}
    files = [f.name for f in project_dir.iterdir() if f.is_file()]
    return {"files": files, "count": len(files)}

