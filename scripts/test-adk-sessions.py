"""Run with the isolated director environment; no cloud calls."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from google.adk.events import Event, EventActions

from execution.repository import MemoryRepository
from sessions.firestore.service import FirestoreSessionService


async def main():
    repo = MemoryRepository()
    repo.atomic(lambda tx: tx.set("users/alice", {"access_enabled": True}))
    repo.atomic(lambda tx: tx.set("projects/project", {"members": {"alice": "owner"}}))
    service = FirestoreSessionService(repo, "project", "alice")
    session = await service.create_session(app_name="vibeshorts", user_id="alice", session_id="session")
    event = Event(
        id="one",
        author="creative_director",
        invocation_id="invocation",
        actions=EventActions(
            state_delta={"scene": 1, "app:policy": "launch", "user:locale": "en", "temp:token": "discard"}
        ),
    )
    await service.append_event(session, event)
    await service.append_event(session, event)
    restarted = FirestoreSessionService(repo, "project", "alice")
    recovered = await restarted.get_session(app_name="vibeshorts", user_id="alice", session_id="session")
    assert len(recovered.events) == 1 and recovered.state["scene"] == 1
    assert recovered.events[0].invocation_id == "invocation"
    assert recovered.state["app:policy"] == "launch" and recovered.state["user:locale"] == "en"
    assert "temp:token" not in recovered.state
    stale = await restarted.get_session(app_name="vibeshorts", user_id="alice", session_id="session")
    await service.append_event(recovered, Event(id="two", author="creative_director"))
    try:
        await service.append_event(stale, Event(id="stale", author="creative_director"))
    except ValueError:
        pass
    else:
        raise AssertionError("Stale session append accepted")
    try:
        await service.get_session(app_name="vibeshorts", user_id="bob", session_id="session")
    except PermissionError:
        pass
    else:
        raise AssertionError("Forged session identity accepted")
    exported = await service.export_session(app_name="vibeshorts", user_id="alice", session_id="session")
    assert len(exported["events"]) == 2
    from google.genai import types

    from sessions.firestore.bridge import JobResultBridge

    latest = await service.get_session(app_name="vibeshorts", user_id="alice", session_id="session")
    await service.append_event(
        latest,
        Event(
            id="call",
            author="creative_director",
            invocation_id="invocation",
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        function_call=types.FunctionCall(
                            id="call-one", name="generate_image", args={"prompt": "product"}
                        )
                    )
                ],
            ),
        ),
    )
    repo.atomic(
        lambda tx: tx.set(
            "projects/project/jobs/job",
            {
                "caller": {"uid": "alice"},
                "job_id": "job",
                "run_id": "run",
                "status": "queued",
                "artifact_ids": [],
                "costs": {},
            },
        )
    )
    bridge = JobResultBridge(service)
    await bridge.associate("session", "call-one", "job")
    assert not await bridge.deliver("session", "call-one")
    repo.atomic(
        lambda tx: tx.set(
            "projects/project/jobs/job",
            {**tx.get("projects/project/jobs/job"), "status": "succeeded", "artifact_ids": ["art-result"]},
        )
    )
    assert await JobResultBridge(restarted).deliver("session", "call-one")
    assert not await bridge.deliver("session", "call-one")
    complete = await service.get_session(app_name="vibeshorts", user_id="alice", session_id="session")
    assert len(complete.events) == 4
    response = complete.events[-1].get_function_responses()[0]
    assert response.id == "call-one" and response.response["artifact_ids"] == ["art-result"]
    await service.delete_session(app_name="vibeshorts", user_id="alice", session_id="session")
    assert not await service.get_session(app_name="vibeshorts", user_id="alice", session_id="session")
    assert not repo.list("adk_sessions")
    assert not repo.list(service._path("vibeshorts", "alice", "session") + "/pending_calls")
    print("ADK sessions: restart, duplicate events, scopes, version, ownership, export and deletion passed")


asyncio.run(main())
