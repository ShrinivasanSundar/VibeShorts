"""Tests for conversation backend: store, service, SSE, and API endpoints."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.models.schemas import CreativeBrief, EditPlan, EditPlanEntry
from src.services.conversation_service import conversation_service
from src.services.conversation_store import conversation_store


client = TestClient(app)


@pytest.mark.anyio
async def test_conversation_store_and_service_lifecycle():
    """Verify conversation creation, turn persistence, and plan updating."""
    proj_id = "test_lifecycle_proj"
    conv = await conversation_service.create_conversation(proj_id)
    assert conv.conversation_id.startswith("conv_")
    assert len(conv.turns) == 1
    assert conv.turns[0].role == "assistant"

    # Send a message through streaming service
    events = []
    async for event in conversation_service.send_message_stream(
        conv.conversation_id, "Please trim the hook"
    ):
        events.append(event)

    assert any(e.event_type == "token" for e in events)
    assert any(e.event_type == "done" for e in events)

    # Check that turns were persisted
    updated = await conversation_service.get_conversation(conv.conversation_id)
    assert updated is not None
    assert len(updated.turns) >= 3  # greeting, user message, assistant response
    assert updated.turns[1].role == "user"
    assert updated.turns[1].content == "Please trim the hook"


def test_conversation_api_endpoints():
    """Test full REST endpoints for conversations."""
    proj_id = "test_api_proj"

    # 1. Create conversation
    res = client.post("/api/v1/conversations", json={"project_id": proj_id})
    assert res.status_code == 201
    data = res.json()
    conv_id = data["conversation_id"]
    assert conv_id.startswith("conv_")

    # 2. Get conversation
    res = client.get(f"/api/v1/conversations/{conv_id}")
    assert res.status_code == 200
    assert len(res.json()["turns"]) == 1

    # 3. Send message
    res = client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"message": "Can you change tone to energetic?"},
    )
    assert res.status_code == 202
    assert res.json()["status"] == "accepted"

    # 4. Get plan (initial is None)
    res = client.get(f"/api/v1/conversations/{conv_id}/plan")
    assert res.status_code == 200
    assert res.json()["plan"] is None

    # 5. Patch plan
    test_plan = {
        "plan_id": f"plan_{proj_id}_v1",
        "project_id": proj_id,
        "revision": 1,
        "total_target_duration": 15.0,
        "cuts": [
            {
                "cut_index": 1,
                "shot_id": "shot_1",
                "source_file_uri": "test.mp4",
                "in_point_sec": 0.0,
                "out_point_sec": 5.0,
                "timeline_duration": 5.0,
                "text_overlay": "Hook",
            }
        ],
    }
    res = client.patch(
        f"/api/v1/conversations/{conv_id}/plan",
        json={"plan": test_plan},
    )
    assert res.status_code == 200
    assert res.json()["plan"]["revision"] == 1

    # 6. Verify plan retrieved
    res = client.get(f"/api/v1/conversations/{conv_id}/plan")
    assert res.status_code == 200
    assert res.json()["plan"]["total_target_duration"] == 15.0

    # 7. List conversations
    res = client.get(f"/api/v1/conversations?project_id={proj_id}")
    assert res.status_code == 200
    assert len(res.json()) >= 1
    assert res.json()[0]["conversation_id"] == conv_id

    # 8. Delete conversation
    res = client.delete(f"/api/v1/conversations/{conv_id}")
    assert res.status_code == 204

    # 9. Verify 404 after deletion
    res = client.get(f"/api/v1/conversations/{conv_id}")
    assert res.status_code == 404
