"""Conversation service — business logic for multi-turn AI chat.

Manages conversation lifecycle, builds Gemini context from persisted history,
and handles both streaming and deterministic (fallback) response generation.
"""

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, List, Optional

from src.core.config import settings
from src.core.gcp import gcp_manager
from src.core.logging import logger
from src.models.schemas import (
    Conversation,
    ConversationTurn,
    CreativeBrief,
    EditPlan,
    EditPlanEntry,
    StreamEvent,
)
from src.services.conversation_store import conversation_store


# ─── Gemini system prompt ────────────────────────────────────────────

SYSTEM_PROMPT = """You are the AI Creative Director & Editor of VibeShorts, a 9:16 short-form video engine.
You help users create, edit, and refine short-form video content (TikTok, Instagram Reels, DTC ads).

Your capabilities:
- Plan and assemble video edits from raw footage
- Trim hooks, swap shots, reorder the timeline
- Update captions, text overlays, and subtitle styles
- Adjust creative tone (energetic, dramatic, educational, humorous, minimalist)
- Trigger re-renders of the current edit plan

When the user requests a timeline change, respond conversationally AND output a structured JSON block at the end:
```json
{"action": "<action_type>", "updated_cuts": [...], "suggested_prompts": ["...", "...", "..."]}
```

Possible action types: "plan_updated", "brief_updated", "re-render_ready", "advice"
If no structured change is needed, just respond conversationally with action "advice".

Keep responses concise and in a director-style creative voice. Use emoji sparingly but effectively.
"""


class ConversationService:
    """Orchestrates multi-turn conversation with Gemini and deterministic fallbacks."""

    def __init__(self):
        self.store = conversation_store

    # ─── Conversation Lifecycle ─────────────────────────────────────

    async def create_conversation(
        self, project_id: str, brief: Optional[CreativeBrief] = None
    ) -> Conversation:
        """Create a new conversation with an initial system greeting."""
        conv = await self.store.create_conversation(project_id, brief)

        # Add system greeting as first turn
        greeting = ConversationTurn(
            id=f"turn_{uuid.uuid4().hex[:8]}",
            role="assistant",
            content=(
                "Hello! I'm your AI Creative Director. Upload raw footage or "
                "tell me what 9:16 short-form cut you'd like to create today."
            ),
            timestamp=datetime.now(timezone.utc),
            action=None,
        )
        await self.store.add_turn(conv.conversation_id, greeting)
        if greeting not in conv.turns:
            conv.turns.append(greeting)

        return conv

    async def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        return await self.store.get_conversation(conversation_id)

    async def list_conversations(self, project_id: str) -> List[Conversation]:
        return await self.store.list_conversations(project_id)

    async def delete_conversation(self, conversation_id: str) -> bool:
        return await self.store.delete_conversation(conversation_id)

    # ─── Send Message (Streaming) ───────────────────────────────────

    async def send_message_stream(
        self, conversation_id: str, user_message: str
    ) -> AsyncGenerator[StreamEvent, None]:
        """Process a user message and yield streaming SSE events.

        Flow:
        1. Persist the user turn
        2. Build Gemini context from conversation history
        3. Stream Gemini response token-by-token as StreamEvents
        4. Parse final response for structured actions (plan updates, etc.)
        5. Persist the assistant turn
        """
        conv = await self.store.get_conversation(conversation_id)
        if not conv:
            yield StreamEvent(event_type="error", content="Conversation not found")
            return

        # 1. Persist user turn
        user_turn = ConversationTurn(
            id=f"turn_{uuid.uuid4().hex[:8]}",
            role="user",
            content=user_message,
            timestamp=datetime.now(timezone.utc),
        )
        await self.store.add_turn(conversation_id, user_turn)

        # 2. Generate assistant turn ID
        assistant_turn_id = f"turn_{uuid.uuid4().hex[:8]}"

        # 3. Attempt Gemini streaming, fall back to deterministic
        if gcp_manager.genai_client is not None:
            full_response = ""
            try:
                async for event in self._stream_gemini_response(conv, user_message, assistant_turn_id):
                    if event.event_type == "token":
                        full_response += event.content or ""
                    yield event

                # 4. Parse structured actions from the full response
                action, plan_update, brief_update, prompts = self._parse_structured_response(
                    full_response, conv
                )

                if plan_update:
                    await self.store.update_plan(conversation_id, plan_update)
                    yield StreamEvent(
                        event_type="plan_update",
                        plan=plan_update,
                        action=action,
                        turn_id=assistant_turn_id,
                    )

                if brief_update:
                    await self.store.update_brief(conversation_id, brief_update)

                if action:
                    yield StreamEvent(
                        event_type="action",
                        action=action,
                        turn_id=assistant_turn_id,
                        suggested_prompts=prompts,
                    )

                # 5. Persist assistant turn
                assistant_turn = ConversationTurn(
                    id=assistant_turn_id,
                    role="assistant",
                    content=full_response,
                    timestamp=datetime.now(timezone.utc),
                    action=action,
                )
                await self.store.add_turn(conversation_id, assistant_turn)

                yield StreamEvent(
                    event_type="done",
                    turn_id=assistant_turn_id,
                    suggested_prompts=prompts,
                )
                return

            except Exception as e:
                logger.warning(f"Gemini streaming failed, falling back to deterministic: {e}")

        # Deterministic fallback
        async for event in self._deterministic_fallback(
            conv, user_message, assistant_turn_id, conversation_id
        ):
            yield event

    # ─── Gemini Streaming ───────────────────────────────────────────

    async def _stream_gemini_response(
        self,
        conv: Conversation,
        user_message: str,
        turn_id: str,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream tokens from Gemini using conversation history as context."""
        from google.genai import types

        system_context = self._build_system_context(conv)
        chat_history = self._build_chat_history(conv)

        # Add the current user message
        chat_history.append({"role": "user", "parts": [{"text": user_message}]})

        full_prompt = f"{system_context}\n\n---\n\nConversation so far:\n"
        for msg in chat_history:
            role = msg["role"]
            text = msg["parts"][0]["text"]
            full_prompt += f"\n{role.upper()}: {text}"

        # Use streaming generation
        response = gcp_manager.genai_client.models.generate_content_stream(
            model=settings.GEMINI_DIRECTOR_MODEL,
            contents=full_prompt,
            config=types.GenerateContentConfig(
                temperature=0.4,
            ),
        )

        for chunk in response:
            if chunk.text:
                yield StreamEvent(
                    event_type="token",
                    content=chunk.text,
                    turn_id=turn_id,
                )
                # Small yield to allow SSE flushing
                await asyncio.sleep(0)

    # ─── Deterministic Fallback ─────────────────────────────────────

    async def _deterministic_fallback(
        self,
        conv: Conversation,
        user_message: str,
        turn_id: str,
        conversation_id: str,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Keyword-based fallback when Gemini is unavailable."""
        lower = user_message.lower()
        plan = conv.current_plan
        brief = conv.current_brief
        updated_plan = plan.model_copy(deep=True) if plan else None
        resp_msg = ""
        action = "advice"
        prompts = ["✂️ Trim first cut by 1s", "✨ Add caption: 'Must Have'", "🚀 Re-render final video"]

        if "trim" in lower or "shorten" in lower or "hook" in lower:
            if updated_plan and updated_plan.cuts:
                cut0 = updated_plan.cuts[0]
                old_dur = cut0.out_point_sec - cut0.in_point_sec
                new_dur = max(1.5, old_dur * 0.75)
                cut0.out_point_sec = round(cut0.in_point_sec + new_dur, 2)
                updated_plan.revision += 1
                updated_plan.total_target_duration = round(
                    sum(c.timeline_duration for c in updated_plan.cuts), 2
                )
                resp_msg = f"⚡ Trimmed Cut #1 hook to {new_dur:.1f}s for maximum viral retention. Ready to re-render!"
                action = "plan_updated"
            else:
                resp_msg = "I can trim the hook once footage is uploaded and the initial plan is generated!"

        elif "caption" in lower or "text" in lower or "subtitle" in lower:
            if updated_plan and updated_plan.cuts:
                quotes = re.findall(r"['\"](.+?)['\"]", user_message)
                new_text = quotes[0] if quotes else "Game Changer"
                updated_plan.cuts[0].text_overlay = new_text
                updated_plan.revision += 1
                resp_msg = f'✍️ Updated hook caption overlay to "{new_text}". Burned in safe region.'
                action = "plan_updated"
            else:
                resp_msg = "Captions will be aligned to speech and dynamic ASS styles automatically."

        elif "swap" in lower or "switch" in lower or "reverse" in lower:
            if updated_plan and len(updated_plan.cuts) >= 2:
                updated_plan.cuts[0], updated_plan.cuts[1] = updated_plan.cuts[1], updated_plan.cuts[0]
                updated_plan.cuts[0].cut_index = 1
                updated_plan.cuts[1].cut_index = 2
                updated_plan.revision += 1
                resp_msg = "🔄 Swapped Cut #1 and Cut #2 to lead with a high-energy B-roll teaser."
                action = "plan_updated"
            else:
                resp_msg = "You can swap any shots on the timeline or ask me to rearrange them."

        elif any(t in lower for t in ["energetic", "dramatic", "educational", "humorous", "minimalist"]):
            matched = next(
                (t for t in ["energetic", "dramatic", "educational", "humorous", "minimalist"] if t in lower),
                "energetic",
            )
            if brief:
                brief = brief.model_copy()
                brief.tone = matched
                await self.store.update_brief(conversation_id, brief)
            resp_msg = f"🎭 Shifted creative pacing to **{matched.upper()}**. Cut lengths and transitions will adapt."
            action = "brief_updated"

        elif "render" in lower or "generate" in lower or "export" in lower:
            resp_msg = "🎬 Triggering FFmpeg 9:16 re-render pass with updated timeline specifications."
            action = "re-render_ready"

        else:
            resp_msg = (
                "I'm ready to direct your cut! You can ask me to **trim the hook**, **rewrite subtitles**, "
                "**swap shots**, **adjust pacing**, or click on the interactive timeline to edit cuts manually."
            )

        # Stream the response word-by-word to simulate typing
        words = resp_msg.split(" ")
        for i, word in enumerate(words):
            token = word if i == 0 else f" {word}"
            yield StreamEvent(event_type="token", content=token, turn_id=turn_id)
            await asyncio.sleep(0.03)

        # Emit plan update if changed
        if action == "plan_updated" and updated_plan:
            await self.store.update_plan(conversation_id, updated_plan)
            yield StreamEvent(
                event_type="plan_update",
                plan=updated_plan,
                action=action,
                turn_id=turn_id,
            )

        yield StreamEvent(
            event_type="action",
            action=action,
            turn_id=turn_id,
            suggested_prompts=prompts,
        )

        # Persist assistant turn
        assistant_turn = ConversationTurn(
            id=turn_id,
            role="assistant",
            content=resp_msg,
            timestamp=datetime.now(timezone.utc),
            action=action,
        )
        await self.store.add_turn(conversation_id, assistant_turn)

        yield StreamEvent(event_type="done", turn_id=turn_id, suggested_prompts=prompts)

    # ─── Context Building ───────────────────────────────────────────

    def _build_system_context(self, conv: Conversation) -> str:
        """Build the system prompt with current project state."""
        ctx = SYSTEM_PROMPT
        ctx += f"\n\nProject ID: {conv.project_id}"
        if conv.current_brief:
            ctx += f"\nCurrent Brief: {conv.current_brief.model_dump_json()}"
        if conv.current_plan:
            ctx += f"\nCurrent EditPlan: {conv.current_plan.model_dump_json()}"
        return ctx

    def _build_chat_history(self, conv: Conversation, max_turns: int = 20) -> list:
        """Convert recent conversation turns to Gemini message format."""
        messages = []
        recent = conv.turns[-max_turns:]
        for turn in recent:
            role = "user" if turn.role == "user" else "model"
            messages.append({"role": role, "parts": [{"text": turn.content}]})
        return messages

    def _parse_structured_response(
        self, response_text: str, conv: Conversation
    ) -> tuple:
        """Extract structured JSON actions from Gemini's response text."""
        action = None
        plan_update = None
        brief_update = None
        prompts = [
            "✂️ Trim first cut by 1s",
            "✨ Add punchy caption",
            "🚀 Re-render final video",
        ]

        # Try to find JSON block in response
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL)
        if not json_match:
            json_match = re.search(r"\{[^{}]*\"action\"[^{}]*\}", response_text, re.DOTALL)

        if json_match:
            try:
                parsed = json.loads(json_match.group(1) if "```" in json_match.group(0) else json_match.group(0))
                action = parsed.get("action")
                prompts = parsed.get("suggested_prompts", prompts)

                if parsed.get("updated_cuts") and conv.current_plan:
                    plan_update = conv.current_plan.model_copy(deep=True)
                    plan_update.cuts = [EditPlanEntry(**c) for c in parsed["updated_cuts"]]
                    plan_update.revision += 1
            except (json.JSONDecodeError, Exception) as e:
                logger.debug(f"Could not parse structured JSON from Gemini response: {e}")

        return action, plan_update, brief_update, prompts

    # ─── Plan Management ────────────────────────────────────────────

    async def update_plan(self, conversation_id: str, plan: EditPlan) -> None:
        """Manual plan update from the timeline editor UI."""
        await self.store.update_plan(conversation_id, plan)

        # Record a system turn noting the manual edit
        system_turn = ConversationTurn(
            id=f"turn_{uuid.uuid4().hex[:8]}",
            role="system",
            content=f"Timeline updated to Revision {plan.revision} ({plan.total_target_duration}s total).",
            timestamp=datetime.now(timezone.utc),
            action="plan_updated",
        )
        await self.store.add_turn(conversation_id, system_turn)

    async def get_plan(self, conversation_id: str) -> Optional[EditPlan]:
        """Get the current plan for a conversation."""
        conv = await self.store.get_conversation(conversation_id)
        return conv.current_plan if conv else None


# Module-level singleton
conversation_service = ConversationService()
