import hashlib

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from execution.dispatch import Reconciler
from execution.runtime import Runtime
from execution.workflow import WorkflowScheduler
from providers.image import ImageOutput
from providers.studio import StudioProvider
from tools.commands import project_path
from tools.contracts.errors import AppError
from tools.contracts.studio import (
    ApprovalDecision,
    Composition,
    ConversationAction,
    ConversationCreate,
    ConversationMessage,
    StudioCommand,
)


@pytest.fixture
def chat(runtime, alice, project, monkeypatch):
    original = StudioProvider.generate

    def fixture(self, request, references, snapshot, job):
        if self.kind == "render":
            clips = self.commands.get_hyperframe(alice, project, request.composition_artifact_id).data[
                "manifest"
            ]["timeline"]["clips"]
            aid = next(c["artifact_id"] for c in clips if c["kind"] == "video")
            data, mime = self.commands.asset_content(alice, project, aid)
            return ImageOutput(data, mime)
        return original(self, request, references, snapshot, job)

    monkeypatch.setattr(StudioProvider, "generate", fixture)
    return runtime.commands.create_conversation(
        alice, project, ConversationCreate(idempotency_key="chat")
    ).data["id"]


def tick(runtime, project, times=1):
    for _ in range(times):
        restarted = Runtime(runtime.commands)
        WorkflowScheduler(restarted.commands).sweep()
        for job in runtime.commands.repo.list(project_path(project, "jobs")):
            if job["status"] == "queued":
                restarted.worker.execute(project, job["job_id"])


def state(runtime, alice, project, chat):
    return runtime.commands.conversation_state(alice, project, chat).data


def approve(runtime, alice, project, approval):
    return runtime.commands.decide_approval(
        alice,
        project,
        approval["id"],
        ApprovalDecision(
            idempotency_key="approve:" + approval["id"],
            target_artifact_id=approval["target_artifact_id"],
            approved=True,
        ),
    )


def start(runtime, alice, project, chat, text="A 6 second story about a little robot"):
    runtime.commands.send_message(
        alice, project, chat, ConversationMessage(idempotency_key="idea", text=text, duration_seconds=6)
    )
    tick(runtime, project, 5)
    return state(runtime, alice, project, chat)


def finish(runtime, alice, project, chat):
    for _ in range(35):
        tick(runtime, project)
        current = state(runtime, alice, project, chat)
        if (
            current["run"]
            and current["run"]["approval"]
            and current["run"]["approval"]["decision"] == "pending"
        ):
            approve(runtime, alice, project, current["run"]["approval"])
        if current["run"] and current["run"]["status"] == "succeeded":
            tick(runtime, project)
            return state(runtime, alice, project, chat)
    pytest.fail(str(current))


def test_guided_scene_gates_restart_and_export(runtime, alice, project, chat):
    first = start(runtime, alice, project, chat)
    assert first["run"]["approval"]["kind"] == "storyboard"
    assert not any(j["kind"] == "image" for j in runtime.commands.repo.list(project_path(project, "jobs")))
    approve(runtime, alice, project, first["run"]["approval"])
    tick(runtime, project, 8)
    current = state(runtime, alice, project, chat)
    assert current["run"]["approval"]["kind"] == "scene", current
    assert current["run"]["approval"]["scene_id"] == "scene-1"
    assert not any(k.startswith("scene-2:") for k in current["run"]["workflow"]["children"])
    assert any(b["kind"] == "scene" for m in current["messages"] for b in m["blocks"])
    completed = finish(runtime, alice, project, chat)
    assert completed["conversation"]["composition_head"]
    assert any(b["kind"] == "export" for m in completed["messages"] for b in m["blocks"])
    before = len(completed["messages"])
    tick(runtime, project, 3)
    assert len(state(runtime, alice, project, chat)["messages"]) == before


def test_storyboard_only_revise_before_production_and_stale_approval(runtime, alice, project, chat):
    current = start(runtime, alice, project, chat, "Just write the storyboard for a 6 second robot story")
    old_approval = current["run"]["approval"]
    runtime.commands.send_message(
        alice,
        project,
        chat,
        ConversationMessage(idempotency_key="revise", text="Change scene 2 to a sunny beach"),
    )
    tick(runtime, project, 5)
    new = state(runtime, alice, project, chat)
    assert new["run"]["run_id"] != current["run"]["run_id"]
    assert new["run"]["approval"]["kind"] == "storyboard"
    assert not any(j["kind"] == "image" for j in runtime.commands.repo.list(project_path(project, "jobs")))
    with pytest.raises(AppError, match="Approval already decided"):
        approve(runtime, alice, project, old_approval)
    story = runtime.commands.get_storyboard(alice, project, new["conversation"]["storyboard_head"]).data
    assert story["scenes"][1]["visual_prompt"] == "Change scene 2 to a sunny beach"


def test_copy_revision_reuses_generated_scene(runtime, alice, project, chat):
    current = start(runtime, alice, project, chat)
    approve(runtime, alice, project, current["run"]["approval"])
    tick(runtime, project, 8)
    before = state(runtime, alice, project, chat)
    prepared = before["run"]["workflow"]["children"]["scene-1:prepared"]
    runtime.commands.send_message(
        alice,
        project,
        chat,
        ConversationMessage(idempotency_key="copy", text='Change scene 1 copy to "Hello robot"'),
    )
    tick(runtime, project, 5)
    after = state(runtime, alice, project, chat)
    assert after["run"]["workflow"]["children"]["scene-1:prepared"] == prepared
    assert after["run"]["approval"]["kind"] == "storyboard"


def test_conversation_heads_and_approvals_are_isolated(runtime, alice, project, chat):
    start(runtime, alice, project, chat)
    first = finish(runtime, alice, project, chat)
    another = runtime.commands.create_conversation(
        alice, project, ConversationCreate(idempotency_key="second")
    ).data["id"]
    start(runtime, alice, project, another)
    second = finish(runtime, alice, project, another)
    h1 = first["conversation"]["composition_head"]
    h2 = second["conversation"]["composition_head"]
    assert h1 != h2
    assert runtime.commands.get_hyperframe(alice, project, conversation_id=chat).data["artifact_id"] == h1
    assert runtime.commands.studio_state(alice, project, chat).data["project"]["composition_head"] == h1
    assert runtime.commands.repo.get(project_path(project)).get("composition_head") is None
    spec = runtime.commands.get_hyperframe(alice, project, h1).data["manifest"]["timeline"]
    with pytest.raises(AppError, match="Composition head advanced"):
        runtime.commands.submit_job(
            alice,
            StudioCommand(
                project_id=project,
                conversation_id=another,
                idempotency_key="wrong",
                input=Composition.model_validate({**spec, "expected_head": h1}),
            ),
            "composition",
        )


def test_message_idempotency_pagination_and_access(runtime, alice, bob, project, chat):
    body = ConversationMessage(idempotency_key="same", text="Just write a storyboard")
    a = runtime.commands.send_message(alice, project, chat, body)
    assert runtime.commands.send_message(alice, project, chat, body) == a
    with pytest.raises(AppError):
        runtime.commands.send_message(
            alice, project, chat, ConversationMessage(idempotency_key="same", text="Another idea")
        )
    with pytest.raises(AppError):
        runtime.commands.conversation_state(bob, project, chat)
    tick(runtime, project, 5)
    page = runtime.commands.conversation_state(alice, project, chat, limit=1).data
    assert page["next_cursor"]
    next_page = runtime.commands.conversation_state(alice, project, chat, cursor=page["next_cursor"]).data
    assert all(m["sequence"] > page["messages"][0]["sequence"] for m in next_page["messages"])


def test_stop_cancels_queued_requests(runtime, alice, project, chat):
    runtime.commands.send_message(
        alice, project, chat, ConversationMessage(idempotency_key="queued", text="Make a robot story")
    )
    runtime.commands.conversation_action(
        alice, project, chat, ConversationAction(idempotency_key="stop", action="cancel")
    )
    tick(runtime, project, 3)
    assert state(runtime, alice, project, chat)["messages"][0]["status"] == "cancelled"
    assert not runtime.commands.repo.list(project_path(project, "jobs"))


def test_rest_conversation_routes(runtime, alice, project, chat):
    client = TestClient(create_app(runtime))
    token = alice.uid
    headers = {"Authorization": "Bearer " + token}
    base = f"/v1/projects/{project}/conversations"
    assert client.get(base, headers=headers).status_code == 200
    response = client.post(
        base + f"/{chat}/messages", headers=headers, json={"idempotency_key": "rest", "text": "A robot story"}
    )
    assert response.status_code == 202
    assert response.json()["data"]["message_id"]
    assert client.get(base + f"/{chat}", headers=headers).status_code == 200


def test_revision_waits_for_current_scene_to_finish(runtime, alice, project, chat):
    current = start(runtime, alice, project, chat)
    approve(runtime, alice, project, current["run"]["approval"])
    tick(runtime, project)  # The first keyframe is ready; the video is not created yet.
    old_run_id = current["run"]["run_id"]
    runtime.commands.send_message(
        alice,
        project,
        chat,
        ConversationMessage(idempotency_key="during-generation", text="Change scene 1 to a moonlit garden"),
    )
    tick(runtime, project, 8)
    old = runtime.commands.get_run(alice, project, old_run_id)
    assert old.status == "cancelled"
    prepared = old.workflow["children"]["scene-1:prepared"]
    assert runtime.commands.get_job(alice, project, prepared).status == "succeeded"
    assert "scene-2:keyframe" not in old.workflow["children"]
    revised = state(runtime, alice, project, chat)
    assert revised["run"]["approval"]["kind"] == "storyboard"
    assert "scene-1:prepared" not in revised["run"]["workflow"]["children"]


def test_failed_scene_retry_retains_new_job_and_is_idempotent(runtime, alice, project, chat, monkeypatch):
    current = start(runtime, alice, project, chat)
    approve(runtime, alice, project, current["run"]["approval"])
    original = runtime.commands.provider.generate

    def fail(*args):
        raise AppError("FIXTURE_FAILURE", "Try this step again")

    monkeypatch.setattr(runtime.commands.provider, "generate", fail)
    tick(runtime, project, 2)
    failed = state(runtime, alice, project, chat)
    assert failed["run"]["status"] == "failed"
    old_id = failed["run"]["workflow"]["children"]["scene-1:keyframe"]
    monkeypatch.setattr(runtime.commands.provider, "generate", original)
    body = ConversationAction(idempotency_key="retry-once", action="retry")
    result = runtime.commands.conversation_action(alice, project, chat, body)
    assert runtime.commands.conversation_action(alice, project, chat, body) == result
    run_doc = runtime.commands.repo.get(project_path(project, "runs", failed["run"]["run_id"]))
    new_id = run_doc["workflow"]["children"]["scene-1:keyframe"]
    assert new_id != old_id and new_id in run_doc["job_ids"]
    tick(runtime, project, 8)
    assert state(runtime, alice, project, chat)["run"]["approval"]["kind"] == "scene"


def test_standalone_failure_is_visible_and_retry_is_idempotent(runtime, alice, project, chat):
    handle = runtime.commands.submit_job(
        alice,
        StudioCommand(
            project_id=project, conversation_id=chat, idempotency_key="save-failure", input=Composition()
        ),
        "composition",
    )
    claimed = runtime.worker.claim(project, handle.job_id)
    error = AppError("FIXTURE_FAILURE", "The edit could not be saved")
    runtime.worker.fail(claimed, error)
    runtime.worker.fail(claimed, error)
    messages = state(runtime, alice, project, chat)["messages"]
    assert len(messages) == 1
    assert messages[0]["text"] == error.payload.message
    assert messages[0]["blocks"][0]["retryable"]
    retry = ConversationAction(idempotency_key="retry-save", action="retry", job_id=handle.job_id)
    result = runtime.commands.conversation_action(alice, project, chat, retry)
    duplicate = runtime.commands.conversation_action(
        alice, project, chat, retry.model_copy(update={"idempotency_key": "second-click"})
    )
    assert result == duplicate
    assert result.data["job_id"] != handle.job_id
    runtime.worker.execute(project, result.data["job_id"])
    current = state(runtime, alice, project, chat)
    assert current["conversation"]["composition_head"]
    assert (
        next(j for j in current["operations"] if j["job_id"] == handle.job_id)["retried_by"]
        == result.data["job_id"]
    )


def test_standalone_retry_rejects_wrong_video_and_uncertain_submission(runtime, alice, project, chat):
    handle = runtime.commands.submit_job(
        alice,
        StudioCommand(
            project_id=project, conversation_id=chat, idempotency_key="uncertain-save", input=Composition()
        ),
        "composition",
    )
    runtime.worker.fail(
        runtime.worker.claim(project, handle.job_id), AppError("FIXTURE_FAILURE", "Unknown"), uncertain=True
    )
    another = runtime.commands.create_conversation(
        alice, project, ConversationCreate(idempotency_key="another-retry")
    ).data["id"]
    body = ConversationAction(idempotency_key="no-retry", action="retry", job_id=handle.job_id)
    with pytest.raises(AppError, match="another video"):
        runtime.commands.conversation_action(alice, project, another, body)
    with pytest.raises(AppError, match="confirmed failed"):
        runtime.commands.conversation_action(alice, project, chat, body)


@pytest.mark.parametrize("terminal_invocation", ["current", "unrelated"])
def test_director_call_limit_recovery_and_safe_retry(runtime, alice, project, chat, terminal_invocation):
    runtime.commands.send_message(
        alice,
        project,
        chat,
        ConversationMessage(idempotency_key="limited", text="A 6 second robot story", duration_seconds=6),
    )
    WorkflowScheduler(runtime.commands).sweep()
    job = next(
        j for j in runtime.commands.repo.list(project_path(project, "jobs")) if j["kind"] == "director_turn"
    )
    claimed = runtime.worker.claim(project, job["job_id"])
    runtime.worker.fail(claimed, AppError("DIRECTOR_FAILED", "No reply"), uncertain=True)
    path = "adk_sessions/" + hashlib.sha256(f"vibeshorts:{project}:alice:session-test".encode()).hexdigest()

    def evidence(tx):
        current = tx.get(project_path(project, "jobs", job["job_id"]))
        current["director"] = {
            "session_id": "session-test",
            "invocation_id": "current",
            "last_event_id": "terminal",
        }
        tx.set(project_path(project, "jobs", job["job_id"]), current)
        tx.set(path, {"project_id": project, "user_id": "alice"})
        tx.set(
            path + "/events/model",
            {
                "event": {
                    "invocation_id": "current",
                    "usage_metadata": {"prompt_token_count": 100, "total_token_count": 150},
                }
            },
        )
        tx.set(
            path + "/events/terminal",
            {"event": {"invocation_id": terminal_invocation, "error_code": "LlmCallsLimitExceededError"}},
        )

    runtime.commands.repo.atomic(evidence)
    Reconciler(runtime.commands).sweep()
    if terminal_invocation == "unrelated":
        assert runtime.commands.get_job(alice, project, job["job_id"]).status == "submission_unknown"
        with pytest.raises(AppError, match="confirmed failed"):
            runtime.commands.conversation_action(
                alice,
                project,
                chat,
                ConversationAction(idempotency_key="unsafe", action="retry", job_id=job["job_id"]),
            )
        return
    assert runtime.commands.get_job(alice, project, job["job_id"]).status == "failed"
    ledger = runtime.commands.repo.get("budgets/" + project + "/entries/" + job["job_id"])
    assert ledger["usage"]["total_token_count"] == 150
    WorkflowScheduler(runtime.commands).sweep()
    failed = state(runtime, alice, project, chat)
    assert failed["messages"][-1]["blocks"][0]["retryable"]
    retry = ConversationAction(idempotency_key="safe", action="retry", job_id=job["job_id"])
    result = runtime.commands.conversation_action(alice, project, chat, retry)
    assert runtime.commands.conversation_action(alice, project, chat, retry) == result
    tick(runtime, project, 5)
    recovered = state(runtime, alice, project, chat)
    assert recovered["run"]["approval"]["kind"] == "storyboard"
    assert len([m for m in recovered["messages"] if m["role"] == "user"]) == 1


def test_messages_wait_for_standalone_save_and_stop_cancels_it(runtime, alice, project, chat):
    handle = runtime.commands.submit_job(
        alice,
        StudioCommand(
            project_id=project, conversation_id=chat, idempotency_key="queued-save", input=Composition()
        ),
        "composition",
    )
    runtime.commands.send_message(
        alice, project, chat, ConversationMessage(idempotency_key="after-save", text="What is the status?")
    )
    WorkflowScheduler(runtime.commands).sweep()
    assert state(runtime, alice, project, chat)["messages"][0]["status"] == "queued"
    assert not any(
        j["kind"] == "director_turn" for j in runtime.commands.repo.list(project_path(project, "jobs"))
    )
    runtime.commands.conversation_action(
        alice, project, chat, ConversationAction(idempotency_key="stop-save", action="cancel")
    )
    assert runtime.commands.get_job(alice, project, handle.job_id).status == "cancelled"
    assert state(runtime, alice, project, chat)["messages"][0]["status"] == "cancelled"


def test_generate_completed_scene_invalidates_that_take_and_preserves_other_scenes(
    runtime, alice, project, chat
):
    start(runtime, alice, project, chat)
    completed = finish(runtime, alice, project, chat)
    original = completed["run"]["workflow"]["children"]
    runtime.commands.send_message(
        alice, project, chat, ConversationMessage(idempotency_key="new-take", text="Generate scene 2")
    )
    tick(runtime, project, 5)
    revised = state(runtime, alice, project, chat)
    assert revised["run"]["approval"]["kind"] == "storyboard"
    children = revised["run"]["workflow"]["children"]
    assert "scene-2:prepared" not in children
    assert children["scene-1:prepared"] == original["scene-1:prepared"]
    assert children["scene-3:prepared"] == original["scene-3:prepared"]


def test_revoked_user_does_not_execute_queued_turn(runtime, alice, project, chat):
    runtime.commands.send_message(
        alice, project, chat, ConversationMessage(idempotency_key="revoked", text="A robot story")
    )
    runtime.commands.repo.atomic(
        lambda tx: tx.set("users/alice", {**tx.get("users/alice"), "access_enabled": False})
    )
    tick(runtime, project)
    assert not runtime.commands.repo.list(project_path(project, "jobs"))
    with pytest.raises(AppError):
        state(runtime, alice, project, chat)


def test_continuity_revision_invalidates_downstream_media(runtime, alice, project, chat):
    current = start(runtime, alice, project, chat)
    storyboard = runtime.commands.get_storyboard(
        alice, project, current["conversation"]["storyboard_head"]
    ).data
    from tools.contracts.studio import BriefInput, Storyboard

    plan = Storyboard.model_validate(storyboard)
    plan.scenes[1].continuity_from_scene_id = "scene-1"
    # Install a new immutable plan before starting production.
    old = runtime.commands.repo.get(project_path(project, "runs", current["run"]["run_id"]))
    runtime.commands.submit_job(
        alice,
        StudioCommand(
            project_id=project,
            conversation_id=chat,
            idempotency_key="continuity-plan",
            input=BriefInput(brief="A linked robot story", duration_seconds=6, workflow_mode="guided"),
        ),
        "storyboard",
        storyboard_override=plan.model_dump(),
    )
    tick(runtime, project, 4)
    completed = finish(runtime, alice, project, chat)
    children = completed["run"]["workflow"]["children"]
    assert "scene-2:anchor" in children
    runtime.commands.send_message(
        alice,
        project,
        chat,
        ConversationMessage(idempotency_key="new-opening", text="Change scene 1 to a sunrise"),
    )
    tick(runtime, project, 5)
    revised = state(runtime, alice, project, chat)["run"]["workflow"]["children"]
    assert "scene-1:prepared" not in revised
    assert "scene-2:prepared" not in revised
    assert revised["scene-3:prepared"] == children["scene-3:prepared"]
    assert runtime.commands.get_run(alice, project, old["run_id"]).status == "cancelled"


def test_linking_legacy_approval_keeps_bulk_workflow(runtime, alice, project, chat):
    from tools.contracts.studio import BriefInput

    handle = runtime.commands.create_video(
        alice,
        StudioCommand(
            project_id=project,
            idempotency_key="legacy",
            input=BriefInput(brief="A legacy product launch", duration_seconds=6),
        ),
    )
    tick(runtime, project, 3)
    run = runtime.commands.get_run(alice, project, handle.run_id)
    linked = runtime.commands.create_conversation(
        alice, project, ConversationCreate(idempotency_key="link", run_id=run.run_id)
    ).data
    assert linked["workflow_mode"] == "bulk"
    approval = runtime.commands.repo.get(project_path(project, "approvals", run.pending_approval_id))
    assert approval["conversation_id"] == linked["id"]
    runtime.commands.conversation_action(
        alice,
        project,
        linked["id"],
        ConversationAction(
            idempotency_key="linked-approve",
            action="approve",
            approval_id=approval["id"],
            target_artifact_id=approval["target_artifact_id"],
        ),
    )
    completed = finish(runtime, alice, project, linked["id"])
    assert completed["run"]["workflow"]["mode"] == "bulk"
    assert completed["conversation"]["composition_head"]


def test_submission_failure_does_not_stop_other_conversations(runtime, alice, project, chat, monkeypatch):
    other = runtime.commands.create_conversation(
        alice, project, ConversationCreate(idempotency_key="other")
    ).data["id"]
    original = runtime.commands.submit_job

    def submit(caller, request, kind, **kwargs):
        if kind == "director_turn" and request.conversation_id == chat:
            raise AppError("BUDGET_EXHAUSTED", "Available budget is below the reservation", 409)
        return original(caller, request, kind, **kwargs)

    monkeypatch.setattr(runtime.commands, "submit_job", submit)
    runtime.commands.send_message(
        alice, project, chat, ConversationMessage(idempotency_key="bad", text="A story")
    )
    runtime.commands.send_message(
        alice, project, other, ConversationMessage(idempotency_key="good", text="A robot story")
    )
    tick(runtime, project, 5)
    failed = state(runtime, alice, project, chat)
    assert failed["messages"][0]["status"] == "failed"
    assert "budget" in failed["messages"][-1]["text"]
    assert state(runtime, alice, project, other)["run"]["approval"]["kind"] == "storyboard"


def test_unified_bulk_preferences_review_and_complete_projection(runtime, alice, project, chat):
    from tools.contracts.studio import CreativePreferences

    cid = runtime.commands.create_conversation(
        alice, project, ConversationCreate(idempotency_key="unified", workflow_mode="bulk")
    ).data["id"]
    preferences = CreativePreferences(vibe="cartoon", motion="slow_motion")
    runtime.commands.send_message(
        alice,
        project,
        cid,
        ConversationMessage(
            idempotency_key="idea",
            text="A 6 second robot story",
            duration_seconds=6,
            creative_preferences=preferences,
            workflow_mode="bulk",
        ),
    )
    tick(runtime, project, 5)
    first = state(runtime, alice, project, cid)
    assert first["production"]["storyboard"]["creative_preferences"] == preferences.model_dump()
    assert not any(j["kind"] == "video" for j in runtime.commands.repo.list(project_path(project, "jobs")))
    approve(runtime, alice, project, first["run"]["approval"])
    for _ in range(18):
        tick(runtime, project)
        current = state(runtime, alice, project, cid)
        approval = current["run"]["approval"]
        assert not approval or approval["kind"] != "scene"
        if approval and approval["kind"] == "preview":
            break
    assert current["run"]["approval"]["kind"] == "preview"
    assert all(
        s["frame"]["artifact_id"] and s["video"]["artifact_id"] for s in current["production"]["scenes"]
    )
    videos = [j for j in runtime.commands.repo.list(project_path(project, "jobs")) if j["kind"] == "video"]
    assert all(
        "Visual style: cartoon" in j["input"]["prompt"] and "Slow motion" in j["input"]["prompt"]
        for j in videos
    )
    old_children = current["run"]["workflow"]["children"]
    runtime.commands.send_message(
        alice,
        project,
        cid,
        ConversationMessage(
            idempotency_key="copy",
            text='Change scene 2 caption to "New copy"',
            creative_preferences=preferences,
            workflow_mode="bulk",
        ),
    )
    tick(runtime, project, 5)
    copied = state(runtime, alice, project, cid)
    assert copied["production"]["affected_scene_ids"] == []
    assert copied["run"]["workflow"]["children"]["scene-1:prepared"] == old_children["scene-1:prepared"]
    # Old reused jobs must remain visible even when more than 15 operations exist.
    assert (
        copied["production"]["scenes"][0]["video"]["artifact_id"]
        == current["production"]["scenes"][0]["video"]["artifact_id"]
    )
    runtime.commands.send_message(
        alice,
        project,
        cid,
        ConversationMessage(
            idempotency_key="style",
            text="Change the storyboard style to 3D",
            creative_preferences=CreativePreferences(vibe="3d"),
            workflow_mode="bulk",
        ),
    )
    tick(runtime, project, 5)
    revised = state(runtime, alice, project, cid)
    assert revised["production"]["affected_scene_ids"] == ["scene-1", "scene-2", "scene-3"]
    assert revised["run"]["approval"]["kind"] == "storyboard"
    assert "scene-1:prepared" not in revised["run"]["workflow"]["children"]
    assert len(
        [j for j in runtime.commands.repo.list(project_path(project, "jobs")) if j["kind"] == "video"]
    ) == len(videos)


def test_unified_links_standalone_composition_without_overwriting_project(runtime, alice, bob, project):
    handle = runtime.commands.submit_job(
        alice,
        StudioCommand(project_id=project, idempotency_key="legacy-cut", input=Composition()),
        "composition",
    )
    runtime.worker.execute(project, handle.job_id)
    aid = runtime.commands.get_job(alice, project, handle.job_id).artifact_ids[0]
    body = ConversationCreate(idempotency_key="open-cut", composition_artifact_id=aid, workflow_mode="bulk")
    linked = runtime.commands.create_conversation(alice, project, body).data
    duplicate = runtime.commands.create_conversation(alice, project, body).data
    assert linked["id"] == duplicate["id"]
    assert linked["composition_head"] == aid
    assert runtime.commands.repo.get(project_path(project))["composition_head"] == aid
    assert state(runtime, alice, project, linked["id"])["production"]["stage"] == "preview"
    with pytest.raises(AppError):
        runtime.commands.create_conversation(bob, project, body)
    other = runtime.commands.create_conversation(
        alice, project, ConversationCreate(idempotency_key="other", workflow_mode="bulk")
    ).data
    assert other["composition_head"] is None


def test_unified_revision_converts_replacement_only_to_bulk(runtime, alice, project, chat):
    first = start(runtime, alice, project, chat)
    assert first["run"]["workflow"]["mode"] == "guided"
    runtime.commands.send_message(
        alice,
        project,
        chat,
        ConversationMessage(
            idempotency_key="unified-revision", text="Change scene 2 to a garden", workflow_mode="bulk"
        ),
    )
    tick(runtime, project, 5)
    replacement = state(runtime, alice, project, chat)
    assert replacement["run"]["workflow"]["mode"] == "bulk"
    assert runtime.commands.get_run(alice, project, first["run"]["run_id"]).workflow["mode"] == "guided"


def test_storyboard_cannot_be_approved_while_requested_changes_are_pending(runtime, alice, project, chat):
    first = start(runtime, alice, project, chat)
    runtime.commands.send_message(
        alice,
        project,
        chat,
        ConversationMessage(idempotency_key="pending-change", text="Change scene 2 to a garden"),
    )
    with pytest.raises(AppError, match="Wait for your requested changes"):
        approve(runtime, alice, project, first["run"]["approval"])
    assert not any(j["kind"] == "video" for j in runtime.commands.repo.list(project_path(project, "jobs")))
