import pytest
import test_conversations
from fastapi.testclient import TestClient
from test_conversations import approve, finish, state, tick

from api.main import create_app
from execution.dispatch import Reconciler
from execution.workflow import WorkflowScheduler
from tools.commands import project_path
from tools.contracts.errors import AppError
from tools.contracts.studio import ConversationAction, ConversationCreate, ConversationMessage

chat = test_conversations.chat  # Shared fixture.


def story(runtime, alice, project, chat, seconds=30):
    runtime.commands.send_message(
        alice,
        project,
        chat,
        ConversationMessage(idempotency_key="idea", text=f"A {seconds} second story about a little robot"),
    )
    tick(runtime, project, 5)
    return state(runtime, alice, project, chat)


def remove(runtime, alice, project, chat, scene, key="remove"):
    return runtime.commands.conversation_action(
        alice, project, chat, ConversationAction(idempotency_key=key, action="remove_scene", scene_id=scene)
    )


def documents(runtime, prefix):
    return [p for p in runtime.commands.repo.documents if p == prefix or p.startswith(prefix + "/")]


def test_remove_scene_shortens_video_and_reuses_other_scenes(runtime, alice, project, chat):
    story(runtime, alice, project, chat)
    done = finish(runtime, alice, project, chat)
    children = done["run"]["workflow"]["children"]
    assert len(done["production"]["scenes"]) == 4
    images = len(
        [j for j in runtime.commands.repo.list(project_path(project, "jobs")) if j["kind"] == "image"]
    )

    result = remove(runtime, alice, project, chat, "scene-2").data
    assert result["duration_seconds"] == 22.5
    assert remove(runtime, alice, project, chat, "scene-2").data == result  # Idempotent retry.
    tick(runtime, project, 2)
    after = state(runtime, alice, project, chat)
    plan = runtime.commands.get_storyboard(alice, project, after["conversation"]["storyboard_head"]).data
    assert [s["id"] for s in plan["scenes"]] == ["scene-1", "scene-3", "scene-4"]
    assert plan["duration_seconds"] == 22.5
    reused = after["run"]["workflow"]["children"]
    for key in ("scene-1:prepared", "scene-3:prepared", "scene-4:prepared", "music"):
        assert reused[key] == children[key]
    assert "music:prepared" not in reused and not any(k.startswith("scene-2") for k in reused)
    assert any("Removed scene 2" in m["text"] for m in after["messages"])

    completed = finish(runtime, alice, project, chat)
    assert completed["conversation"]["composition_head"] != done["conversation"]["composition_head"]
    jobs = runtime.commands.repo.list(project_path(project, "jobs"))
    assert len([j for j in jobs if j["kind"] == "image"]) == images  # No scene was regenerated.
    with pytest.raises(AppError, match="at least 3 scenes"):
        remove(runtime, alice, project, chat, "scene-3", key="too-few")


def test_remove_scene_waits_for_running_generation(runtime, alice, project, chat):
    current = story(runtime, alice, project, chat)
    approve(runtime, alice, project, current["run"]["approval"])
    WorkflowScheduler(runtime.commands).sweep()  # Submits the first keyframe without running it.
    with pytest.raises(AppError, match="Wait for the current step"):
        remove(runtime, alice, project, chat, "scene-2")


def test_delete_conversation_erases_it_and_releases_running_work(runtime, alice, project, chat):
    current = story(runtime, alice, project, chat)
    approve(runtime, alice, project, current["run"]["approval"])
    WorkflowScheduler(runtime.commands).sweep()
    queued = [j for j in runtime.commands.repo.list(project_path(project, "jobs")) if j["status"] == "queued"]
    assert queued

    runtime.commands.delete_conversation(alice, project, chat)
    assert not runtime.commands.repo.list(project_path(project, "jobs"))
    assert not runtime.commands.repo.list(project_path(project, "runs"))
    assert not runtime.commands.repo.list(project_path(project, "approvals"))
    assert not documents(runtime, project_path(project, "conversations", chat))
    assert not [p for p in runtime.commands.storage.objects if "/jobs/" in p]
    assert runtime.commands.repo.get("budgets/" + project)["reserved_micros"] == 0
    assert runtime.commands.list_conversations(alice, project).data["conversations"] == []
    with pytest.raises(AppError, match="Conversation not found"):
        state(runtime, alice, project, chat)
    # Background work for the erased video ends quietly instead of stopping the worker.
    assert runtime.worker.execute(project, queued[0]["job_id"]) is False
    WorkflowScheduler(runtime.commands).sweep()
    Reconciler(runtime.commands).sweep()


def test_delete_conversation_keeps_media_another_video_uses(runtime, alice, project, chat):
    story(runtime, alice, project, chat)
    done = finish(runtime, alice, project, chat)
    head = done["conversation"]["composition_head"]
    copy = runtime.commands.create_conversation(
        alice, project, ConversationCreate(idempotency_key="copy", composition_artifact_id=head)
    ).data["id"]
    storyboard = done["conversation"]["storyboard_head"]

    runtime.commands.delete_conversation(alice, project, chat)
    assert runtime.commands.asset_content(alice, project, head)[0]
    clips = runtime.commands.get_hyperframe(alice, project, head).data["manifest"]["timeline"]["clips"]
    for clip in clips:
        if clip.get("artifact_id"):
            assert runtime.commands.asset_content(alice, project, clip["artifact_id"])[0]
    with pytest.raises(AppError):
        runtime.commands.get_asset(alice, project, storyboard)
    assert state(runtime, alice, project, copy)["conversation"]["composition_head"] == head


def test_delete_project_erases_everything_and_is_owner_only(runtime, alice, bob, project, chat):
    story(runtime, alice, project, chat)
    finish(runtime, alice, project, chat)
    with pytest.raises(AppError):
        runtime.commands.delete_project(bob, project)

    runtime.commands.delete_project(alice, project)
    assert not documents(runtime, project_path(project))
    assert not documents(runtime, "budgets/" + project)
    assert not [p for p in runtime.commands.storage.objects if p.startswith(f"projects/{project}/")]
    assert runtime.commands.list_projects(alice).data["projects"] == []
    with pytest.raises(AppError):
        runtime.commands.conversation_state(alice, project, chat)
    WorkflowScheduler(runtime.commands).sweep()
    Reconciler(runtime.commands).sweep()


def test_delete_routes(runtime, alice, project, chat):
    client = TestClient(create_app(runtime))
    headers = {"Authorization": "Bearer " + alice.uid}
    assert client.delete(f"/v1/projects/{project}/conversations/{chat}", headers=headers).status_code == 200
    assert client.delete(f"/v1/projects/{project}/conversations/{chat}", headers=headers).status_code == 404
    assert client.delete(f"/v1/projects/{project}", headers=headers).status_code == 200
    assert client.get("/v1/projects", headers=headers).json()["data"]["projects"] == []
