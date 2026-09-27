"""Firestore persistence layer for conversations.

Provides async CRUD for Conversation documents and ConversationTurn subcollections.
Falls back to an in-memory dict when Firestore is unavailable (local dev without ADC).
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from src.core.logging import logger
from src.models.schemas import (
    Conversation,
    ConversationTurn,
    CreativeBrief,
    EditPlan,
)

# Collection names in Firestore
CONVERSATIONS_COLLECTION = "conversations"
TURNS_SUBCOLLECTION = "turns"


class ConversationStore:
    """Async conversation persistence backed by Firestore with in-memory fallback."""

    def __init__(self):
        self._firestore = None
        self._memory_store: Dict[str, Conversation] = {}
        self._init_firestore()

    def _init_firestore(self) -> None:
        """Attempt to get Firestore client from GCP manager."""
        try:
            from src.core.gcp import gcp_manager
            self._firestore = gcp_manager.firestore_client
            if self._firestore:
                logger.info("ConversationStore: using Firestore backend")
            else:
                logger.warning("ConversationStore: Firestore unavailable, using in-memory fallback")
        except Exception as e:
            logger.warning(f"ConversationStore: Firestore init failed, using in-memory fallback: {e}")

    @property
    def _using_firestore(self) -> bool:
        return self._firestore is not None

    # ─── Create ─────────────────────────────────────────────────────

    async def create_conversation(
        self,
        project_id: str,
        brief: Optional[CreativeBrief] = None,
    ) -> Conversation:
        """Create a new conversation and persist it."""
        conv = Conversation(
            conversation_id=f"conv_{uuid.uuid4().hex[:12]}",
            project_id=project_id,
            current_brief=brief,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        if self._using_firestore:
            doc_ref = self._firestore.collection(CONVERSATIONS_COLLECTION).document(conv.conversation_id)
            await doc_ref.set(conv.model_dump(mode="json"))
        else:
            self._memory_store[conv.conversation_id] = conv

        logger.info(f"Created conversation {conv.conversation_id} for project {project_id}")
        return conv

    # ─── Read ───────────────────────────────────────────────────────

    async def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """Retrieve a conversation by ID, including all turns."""
        if self._using_firestore:
            doc_ref = self._firestore.collection(CONVERSATIONS_COLLECTION).document(conversation_id)
            doc = await doc_ref.get()
            if not doc.exists:
                return None

            data = doc.to_dict()

            # Load turns from subcollection
            turns_ref = doc_ref.collection(TURNS_SUBCOLLECTION)
            turns_query = turns_ref.order_by("timestamp")
            turns_docs = turns_query.stream()
            turns = []
            async for turn_doc in turns_docs:
                turns.append(ConversationTurn(**turn_doc.to_dict()))

            data["turns"] = [t.model_dump(mode="json") for t in turns]
            return Conversation(**data)
        else:
            return self._memory_store.get(conversation_id)

    async def list_conversations(self, project_id: str) -> List[Conversation]:
        """List all conversations for a project (without full turn history)."""
        if self._using_firestore:
            query = (
                self._firestore.collection(CONVERSATIONS_COLLECTION)
                .where("project_id", "==", project_id)
                .order_by("updated_at", direction="DESCENDING")
                .limit(50)
            )
            results = []
            async for doc in query.stream():
                data = doc.to_dict()
                data["turns"] = []  # Don't load turns for listing
                results.append(Conversation(**data))
            return results
        else:
            return [
                c for c in self._memory_store.values()
                if c.project_id == project_id
            ]

    # ─── Add Turn ───────────────────────────────────────────────────

    async def add_turn(self, conversation_id: str, turn: ConversationTurn) -> None:
        """Append a turn to the conversation history."""
        now = datetime.now(timezone.utc)

        if self._using_firestore:
            doc_ref = self._firestore.collection(CONVERSATIONS_COLLECTION).document(conversation_id)
            # Add turn to subcollection
            turn_ref = doc_ref.collection(TURNS_SUBCOLLECTION).document(turn.id)
            await turn_ref.set(turn.model_dump(mode="json"))
            # Update conversation timestamp
            await doc_ref.update({"updated_at": now.isoformat()})
        else:
            conv = self._memory_store.get(conversation_id)
            if conv:
                conv.turns.append(turn)
                conv.updated_at = now

    # ─── Update State ───────────────────────────────────────────────

    async def update_plan(self, conversation_id: str, plan: EditPlan) -> None:
        """Update the current EditPlan on a conversation."""
        now = datetime.now(timezone.utc)

        if self._using_firestore:
            doc_ref = self._firestore.collection(CONVERSATIONS_COLLECTION).document(conversation_id)
            await doc_ref.update({
                "current_plan": plan.model_dump(mode="json"),
                "updated_at": now.isoformat(),
            })
        else:
            conv = self._memory_store.get(conversation_id)
            if conv:
                conv.current_plan = plan
                conv.updated_at = now

    async def update_brief(self, conversation_id: str, brief: CreativeBrief) -> None:
        """Update the current CreativeBrief on a conversation."""
        now = datetime.now(timezone.utc)

        if self._using_firestore:
            doc_ref = self._firestore.collection(CONVERSATIONS_COLLECTION).document(conversation_id)
            await doc_ref.update({
                "current_brief": brief.model_dump(mode="json"),
                "updated_at": now.isoformat(),
            })
        else:
            conv = self._memory_store.get(conversation_id)
            if conv:
                conv.current_brief = brief
                conv.updated_at = now

    # ─── Delete ─────────────────────────────────────────────────────

    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and all its turns."""
        if self._using_firestore:
            doc_ref = self._firestore.collection(CONVERSATIONS_COLLECTION).document(conversation_id)
            doc = await doc_ref.get()
            if not doc.exists:
                return False

            # Delete all turns in subcollection
            turns_ref = doc_ref.collection(TURNS_SUBCOLLECTION)
            async for turn_doc in turns_ref.stream():
                await turn_doc.reference.delete()

            await doc_ref.delete()
            return True
        else:
            return self._memory_store.pop(conversation_id, None) is not None

    # ─── Get Recent Turns ───────────────────────────────────────────

    async def get_recent_turns(
        self, conversation_id: str, limit: int = 20
    ) -> List[ConversationTurn]:
        """Retrieve the most recent N turns for Gemini context window."""
        conv = await self.get_conversation(conversation_id)
        if not conv:
            return []
        return conv.turns[-limit:]


# Module-level singleton
conversation_store = ConversationStore()
