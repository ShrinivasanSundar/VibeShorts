"""Conversation API routes — SSE streaming, multi-turn chat, and plan management.

Endpoints:
    POST   /conversations                           → Create a new conversation
    GET    /conversations/{conversation_id}          → Get conversation + history
    DELETE /conversations/{conversation_id}          → Delete conversation
    GET    /conversations                            → List conversations for a project
    POST   /conversations/{conversation_id}/messages → Send user message (returns 202)
    GET    /conversations/{conversation_id}/stream   → SSE stream for real-time AI response tokens
    GET    /conversations/{conversation_id}/plan     → Get current plan
    PATCH  /conversations/{conversation_id}/plan     → Manual plan edit from timeline UI
    POST   /conversations/{conversation_id}/render   → Trigger re-render of current plan
"""

import asyncio
import json
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.core.config import settings
from src.core.logging import logger
from src.models.schemas import (
    Conversation,
    ConversationTurn,
    CreativeBrief,
    EditPlan,
    FootageIndex,
    SendMessageRequest,
    StreamEvent,
)
from src.services.conversation_service import conversation_service
from src.services.orchestrator import VideoOrchestrator


router = APIRouter(prefix="/conversations", tags=["conversations"])

# In-memory event queues for SSE streaming (per conversation)
_stream_queues: dict[str, list[asyncio.Queue]] = {}

orchestrator = VideoOrchestrator()


# ─── Request / Response Models ──────────────────────────────────────


class CreateConversationRequest(BaseModel):
    project_id: str
    brief: Optional[CreativeBrief] = None


class PlanUpdateRequest(BaseModel):
    plan: EditPlan


class ConversationSummary(BaseModel):
    conversation_id: str
    project_id: str
    created_at: str
    updated_at: str
    turn_count: int
    has_plan: bool


# ─── Conversation Lifecycle ─────────────────────────────────────────


@router.post("", status_code=201)
async def create_conversation(payload: CreateConversationRequest):
    """Create a new conversation for a project."""
    conv = await conversation_service.create_conversation(
        project_id=payload.project_id,
        brief=payload.brief,
    )
    return conv


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str):
    """Retrieve a conversation with full turn history."""
    conv = await conversation_service.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str):
    """Delete a conversation and all its turns."""
    deleted = await conversation_service.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.get("")
async def list_conversations(project_id: str = Query(...)):
    """List all conversations for a project."""
    convs = await conversation_service.list_conversations(project_id)
    return [
        ConversationSummary(
            conversation_id=c.conversation_id,
            project_id=c.project_id,
            created_at=c.created_at.isoformat(),
            updated_at=c.updated_at.isoformat(),
            turn_count=len(c.turns),
            has_plan=c.current_plan is not None,
        )
        for c in convs
    ]


# ─── Messaging ──────────────────────────────────────────────────────


@router.post("/{conversation_id}/messages", status_code=202)
async def send_message(conversation_id: str, payload: SendMessageRequest):
    """Send a user message. The AI response streams via the SSE /stream endpoint.

    Returns 202 immediately. The assistant response is delivered asynchronously
    through the SSE stream.
    """
    conv = await conversation_service.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    turn_id = f"turn_{uuid.uuid4().hex[:8]}"

    # Launch streaming response generation as a background task
    asyncio.create_task(
        _process_message_to_queues(conversation_id, payload.message)
    )

    return {"status": "accepted", "conversation_id": conversation_id}


async def _process_message_to_queues(conversation_id: str, message: str):
    """Generate AI response and push events to all subscribed SSE queues."""
    try:
        async for event in conversation_service.send_message_stream(
            conversation_id, message
        ):
            queues = _stream_queues.get(conversation_id, [])
            for queue in queues:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(f"SSE queue full for conversation {conversation_id}")
    except Exception as e:
        logger.error(f"Error processing message for {conversation_id}: {e}", exc_info=True)
        error_event = StreamEvent(event_type="error", content=str(e))
        for queue in _stream_queues.get(conversation_id, []):
            try:
                queue.put_nowait(error_event)
            except asyncio.QueueFull:
                pass


# ─── SSE Stream ─────────────────────────────────────────────────────


@router.get("/{conversation_id}/stream")
async def stream_events(conversation_id: str):
    """Server-Sent Events endpoint for real-time AI response streaming.

    The frontend subscribes to this endpoint once per conversation.
    Token-by-token chunks, plan updates, and actions are pushed as SSE events.
    """
    conv = await conversation_service.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    queue: asyncio.Queue[StreamEvent] = asyncio.Queue(maxsize=500)

    # Register this queue for the conversation
    if conversation_id not in _stream_queues:
        _stream_queues[conversation_id] = []
    _stream_queues[conversation_id].append(queue)

    async def event_generator():
        try:
            # Send a heartbeat to confirm connection
            yield f"event: connected\ndata: {json.dumps({'conversation_id': conversation_id})}\n\n"

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    event_data = event.model_dump_json()
                    yield f"event: {event.event_type}\ndata: {event_data}\n\n"
                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield f"event: heartbeat\ndata: {json.dumps({'ts': __import__('time').time()})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            # Unregister queue on disconnect
            if conversation_id in _stream_queues:
                _stream_queues[conversation_id] = [
                    q for q in _stream_queues[conversation_id] if q is not queue
                ]
                if not _stream_queues[conversation_id]:
                    del _stream_queues[conversation_id]

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
        },
    )


# ─── Plan Management ───────────────────────────────────────────────


@router.get("/{conversation_id}/plan")
async def get_plan(conversation_id: str):
    """Get the current EditPlan for a conversation."""
    plan = await conversation_service.get_plan(conversation_id)
    if plan is None:
        return {"plan": None, "message": "No plan generated yet"}
    return {"plan": plan}


@router.patch("/{conversation_id}/plan")
async def update_plan(conversation_id: str, payload: PlanUpdateRequest):
    """Manual plan update from the timeline editor UI."""
    conv = await conversation_service.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await conversation_service.update_plan(conversation_id, payload.plan)

    # Push plan update event to SSE subscribers
    event = StreamEvent(
        event_type="plan_update",
        plan=payload.plan,
        action="plan_updated",
    )
    for queue in _stream_queues.get(conversation_id, []):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    return {"status": "updated", "plan": payload.plan}


@router.post("/{conversation_id}/render")
async def trigger_render(conversation_id: str):
    """Trigger re-render of the current plan with FFmpeg."""
    conv = await conversation_service.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not conv.current_plan:
        raise HTTPException(status_code=400, detail="No plan to render")

    project_dir = settings.STORAGE_DIR / "uploads" / conv.project_id
    media_paths = (
        list(project_dir.glob("*.mp4")) + list(project_dir.glob("*.mov"))
        if project_dir.exists()
        else []
    )

    footage_index = (
        orchestrator.ingest_pipeline.process_project_footage(conv.project_id, media_paths)
        if media_paths
        else FootageIndex(project_id=conv.project_id)
    )

    final_mp4 = settings.OUTPUT_DIR / f"{conv.project_id}_final.mp4"
    orchestrator.ffmpeg_editor.render_edit_plan(conv.current_plan, footage_index, final_mp4)

    video_url = f"/api/v1/videos/{conv.project_id}_final.mp4"

    return {
        "status": "completed",
        "video_url": video_url,
        "plan": conv.current_plan,
    }
