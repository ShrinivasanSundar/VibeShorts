import io
import zipfile

import pytest
from pydantic import ValidationError

from execution.runtime import Runtime
from execution.workflow import WorkflowScheduler
from providers.image import ImageOutput
from providers.studio import StudioProvider
from tools.commands import project_path
from tools.composition.package import build, unpack
from tools.contracts.errors import AppError
from tools.contracts.models import Caller, ImageCommand, ImageInput
from tools.contracts.studio import (
    ApprovalDecision,
    BriefInput,
    Clip,
    Composition,
    RenderInput,
    StudioCommand,
    VideoInput,
)


def submit(runtime, caller, project, kind, input, key):
    request = (ImageCommand if kind == "image" else StudioCommand)(
        project_id=project, idempotency_key=key, input=input
    )
    handle = runtime.commands.submit_job(caller, request, kind)
    runtime.worker.execute(project, handle.job_id)
    job = runtime.commands.get_job(caller, project, handle.job_id)
    assert job.status == "succeeded", job.error
    return job.artifact_ids[0]


def test_studio_immutable_revision_approval_and_conflict(runtime, alice, project):
    image = submit(runtime, alice, project, "image", ImageInput(prompt="Pedestal"), "keyframe")
    spec = Composition(
        duration_seconds=3,
        clips=[
            Clip(id="image", artifact_id=image, kind="image", track=0, start=0, duration=3),
            Clip(id="title", kind="text", track=2, start=0, duration=3, text="<script>safe copy</script>"),
        ],
    )
    artifact = submit(runtime, alice, project, "composition", spec, "composition")
    manifest = runtime.commands.get_hyperframe(alice, project, artifact).data["manifest"]
    assert manifest["input_artifact_ids"] == [image]
    content, _ = runtime.commands.asset_content(alice, project, artifact)
    _, files = unpack(content)
    assert b"&lt;script&gt;safe copy&lt;/script&gt;" in files["index.html"]
    assert all("https://" not in p for p in files)
    with pytest.raises(AppError, match="Composition head"):
        runtime.commands.create_hyperframe(
            alice, StudioCommand(project_id=project, idempotency_key="stale", input=spec)
        )
    with pytest.raises(AppError, match="approved"):
        runtime.commands.render_hyperframe(
            alice,
            StudioCommand(
                project_id=project,
                idempotency_key="unapproved",
                input=RenderInput(composition_artifact_id=artifact, quality="final"),
            ),
        )
    approval = runtime.commands.request_preview_approval(alice, project, artifact, "review").data
    scoped = Caller(uid=alice.uid, auth_time=alice.auth_time, projects=[project])
    decision = ApprovalDecision(idempotency_key="approve", target_artifact_id=artifact, approved=True)
    with pytest.raises(AppError, match="human"):
        runtime.commands.decide_approval(scoped, project, approval["id"], decision)
    runtime.commands.decide_approval(alice, project, approval["id"], decision)
    final = runtime.commands.render_hyperframe(
        alice,
        StudioCommand(
            project_id=project,
            idempotency_key="approved",
            input=RenderInput(composition_artifact_id=artifact, quality="final"),
        ),
    )
    assert final.status == "queued"
    edited = spec.model_copy(update={"expected_head": artifact, "title": "Revision two"})
    revision = submit(runtime, alice, project, "composition", edited, "edit")
    assert revision != artifact
    assert runtime.commands.get_hyperframe(alice, project, artifact).data["current"] is False
    with pytest.raises(AppError, match="approved"):
        runtime.commands.render_hyperframe(
            alice,
            StudioCommand(
                project_id=project,
                idempotency_key="new-unapproved",
                input=RenderInput(composition_artifact_id=revision, quality="final"),
            ),
        )


def test_timeline_and_video_combination_validation():
    with pytest.raises(ValidationError):
        Composition(duration_seconds=2, clips=[Clip(id="title", kind="text", track=2, start=1, duration=2)])
    with pytest.raises(ValidationError):
        VideoInput(prompt="test", first_frame_artifact_id="a", resolution="1080p", source_duration_seconds=6)


def test_package_rejects_path_traversal_and_tampering():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../escaped", "bad")
    with pytest.raises(AppError):
        unpack(stream.getvalue())
    valid = build(Composition(duration_seconds=1), {})
    stream = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(valid)) as source, zipfile.ZipFile(stream, "w") as archive:
        for name in source.namelist():
            archive.writestr(name, b"changed" if name == "index.html" else source.read(name))
    with pytest.raises(AppError):
        unpack(stream.getvalue())


def test_known_video_handle_retries_poll_only(runtime, alice, project, monkeypatch, png):
    image = submit(runtime, alice, project, "image", ImageInput(prompt="frame"), "frame")

    class Provider:
        submits = 0
        polls = 0

        def snapshot(self):
            return {
                "route": "fixture",
                "model": "test",
                "location": "local",
                "api_version": "1",
                "rate": {},
                "reservation_micros": 0,
            }

        def submit_video(self, *args):
            self.submits += 1
            return {"name": "known-operation"}

        def poll_video(self, *args):
            self.polls += 1
            raise TimeoutError("retrieval interrupted")

    # Accept with the real adapter; simulate a known live operation persisted before a crash.
    handle = runtime.commands.generate_video(
        alice,
        StudioCommand(
            project_id=project,
            idempotency_key="video",
            input=VideoInput(prompt="plate", first_frame_artifact_id=image),
        ),
    )
    path = project_path(project, "jobs", handle.job_id)

    def wait(tx):
        job = tx.get(path)
        job.update(
            provider_operation={"name": "known-operation"},
            candidate_path="known-candidate",
            attempt=1,
            status="waiting_for_provider",
            next_poll_at=0,
        )
        tx.set(path, job)

    runtime.commands.repo.atomic(wait)
    provider = Provider()
    monkeypatch.setattr(runtime.commands, "provider_for", lambda kind: provider)
    assert runtime.worker.execute(project, handle.job_id)
    restarted = Runtime(runtime.commands)
    runtime.commands.clock.advance(11)
    assert restarted.worker.execute(project, handle.job_id)
    assert provider.submits == 0 and provider.polls == 2
    assert runtime.commands.repo.get(path)["provider_operation"]["name"] == "known-operation"


def test_fixture_workflow_survives_restart_and_two_gates(runtime, alice, project, monkeypatch):
    original = StudioProvider.generate

    def render_fixture(self, request, references, snapshot, job):
        if self.kind == "render":
            # Render mechanics have a separate real HyperFrames acceptance script.
            video_id = next(
                c["artifact_id"]
                for c in self.commands.get_hyperframe(alice, project, request.composition_artifact_id).data[
                    "manifest"
                ]["timeline"]["clips"]
                if c["kind"] == "video"
            )
            data, mime = self.commands.asset_content(alice, project, video_id)
            return ImageOutput(data, mime)
        return original(self, request, references, snapshot, job)

    monkeypatch.setattr(StudioProvider, "generate", render_fixture)
    handle = runtime.commands.create_video(
        alice,
        StudioCommand(
            project_id=project,
            idempotency_key="short",
            input=BriefInput(brief="Launch a new creative studio", duration_seconds=6),
        ),
    )
    runtime.worker.execute(project, handle.job_id)
    scheduler = WorkflowScheduler(runtime.commands)
    scheduler.sweep()
    run = runtime.commands.get_run(alice, project, handle.run_id)
    assert run.status == "needs_approval"
    assert len(runtime.commands.repo.list(project_path(project, "jobs"))) == 1
    runtime.commands.decide_approval(
        alice,
        project,
        run.approval["id"],
        ApprovalDecision(
            idempotency_key="approve-story",
            target_artifact_id=run.approval["target_artifact_id"],
            approved=True,
        ),
    )
    for _ in range(14):
        restarted = Runtime(runtime.commands)
        WorkflowScheduler(restarted.commands).sweep()
        for job in restarted.commands.repo.list(project_path(project, "jobs")):
            if job["status"] == "queued":
                restarted.worker.execute(project, job["job_id"])
        run = restarted.commands.get_run(alice, project, handle.run_id)
        if run.pending_approval_id and run.approval["kind"] == "preview":
            break
    assert run.status == "needs_approval", run
    assert run.approval["kind"] == "preview"
    assert not any(
        j["kind"] == "render" and j["input"]["quality"] == "final"
        for j in runtime.commands.repo.list(project_path(project, "jobs"))
    )
    runtime.commands.decide_approval(
        alice,
        project,
        run.approval["id"],
        ApprovalDecision(
            idempotency_key="approve-preview",
            target_artifact_id=run.approval["target_artifact_id"],
            approved=True,
        ),
    )
    for _ in range(3):
        scheduler.sweep()
        for job in runtime.commands.repo.list(project_path(project, "jobs")):
            if job["status"] == "queued":
                runtime.worker.execute(project, job["job_id"])
    run = runtime.commands.get_run(alice, project, handle.run_id)
    assert run.status == "succeeded", run
    assert run.workflow["export_artifact_id"]
    assert runtime.commands.repo.get("budgets/" + project)["reserved_micros"] == 0
    assert runtime.commands.provider.calls == 3
    assert all(j["attempt"] == 1 for j in runtime.commands.repo.list(project_path(project, "jobs")))

    old_children = run.workflow["children"]
    revised = runtime.commands.create_video(
        alice,
        StudioCommand(
            project_id=project,
            idempotency_key="selective-revision",
            input=BriefInput(
                brief="Revise opening visual",
                duration_seconds=6,
                revision_of_run_id=run.run_id,
                expected_head=run.workflow["composition_artifact_id"],
                scene_overrides={"scene-1": "A new cinematic opening with gold lighting"},
            ),
        ),
    )
    for _ in range(20):
        scheduler.sweep()
        for job in runtime.commands.repo.list(project_path(project, "jobs")):
            if job["status"] == "queued":
                runtime.worker.execute(project, job["job_id"])
        revision = runtime.commands.get_run(alice, project, revised.run_id)
        if revision.approval and revision.approval["decision"] == "pending":
            runtime.commands.decide_approval(
                alice,
                project,
                revision.approval["id"],
                ApprovalDecision(
                    idempotency_key="selective:" + revision.approval["id"],
                    target_artifact_id=revision.approval["target_artifact_id"],
                    approved=True,
                ),
            )
        if revision.status == "succeeded":
            break
    assert revision.status == "succeeded", revision
    assert runtime.commands.provider.calls == 4  # Only the changed opening purchases a new keyframe.
    assert revision.workflow["children"]["scene-2:prepared"] == old_children["scene-2:prepared"]
    assert revision.workflow["children"]["music:prepared"] == old_children["music:prepared"]
    assert revision.workflow["children"]["scene-1:prepared"] != old_children["scene-1:prepared"]


def test_fixture_edit_preserves_inputs_and_invalidates_dependencies(runtime, alice, project):
    from tools.contracts.studio import EditInput

    image = submit(runtime, alice, project, "image", ImageInput(prompt="Frame"), "frame-edit")
    first = submit(
        runtime,
        alice,
        project,
        "composition",
        Composition(
            duration_seconds=2,
            clips=[
                Clip(id="plate", kind="image", artifact_id=image, track=0, start=0, duration=2),
                Clip(id="copy", kind="text", track=2, start=0, duration=2, text="Hello world"),
            ],
        ),
        "first-edit",
    )
    revised = submit(
        runtime,
        alice,
        project,
        "edit",
        EditInput(expected_head=first, instruction='replace "Hello" with "Goodbye"'),
        "language-edit",
    )
    timeline = runtime.commands.get_hyperframe(alice, project, revised).data["manifest"]["timeline"]
    assert timeline["clips"][1]["text"] == "Goodbye world"
    assert timeline["clips"][0]["artifact_id"] == image
    assert runtime.commands._artifact(project, revised)["parent_id"] == first
    assert {image, first, revised} <= set(
        runtime.commands.invalidated_assets(alice, project, image).data["artifact_ids"]
    )
    assert runtime.commands.provider.calls == 1


def test_rest_import_preview_and_scoped_storyboard_read(runtime, alice, bob, project, png):
    from fastapi.testclient import TestClient

    from apps.api.main import create_app

    with TestClient(create_app(runtime), headers={"Authorization": "Bearer alice"}) as http:
        base = f"/v1/projects/{project}"
        response = http.post(
            base + "/uploads",
            json={
                "title": "Reference",
                "mime_type": "image/png",
                "size_bytes": len(png),
                "idempotency_key": "import",
            },
        )
        assert response.status_code == 200, response.text
        upload = response.json()["data"]["upload_id"]
        assert (
            http.put(
                base + f"/uploads/{upload}/content", content=png, headers={"Content-Type": "image/png"}
            ).status_code
            == 200
        )
        response = http.post(
            base + "/uploads/complete", json={"upload_id": upload, "idempotency_key": "publish"}
        )
        assert response.status_code == 200, response.text
        image = response.json()["data"]["id"]
        composition = submit(
            runtime,
            alice,
            project,
            "composition",
            Composition(
                duration_seconds=2,
                clips=[Clip(id="plate", kind="image", artifact_id=image, track=0, start=0, duration=2)],
            ),
            "rest-composition",
        )
        response = http.get(base + f"/compositions/{composition}/preview")
        assert response.status_code == 200, response.text
        html = response.json()["data"]["html"]
        assert 'src="assets/' not in html
        assert "data:image/png;base64," in html and "data:font/woff2;base64," in html
        assert "connect-src &#x27;none&#x27;" in html
        assert http.get(base + "/studio").json()["data"]["provider_route"] == "fixture"
    with pytest.raises(AppError, match="permission"):
        runtime.commands.get_storyboard(bob, project, "nonexistent")


def test_cancelled_workflow_cannot_be_revived_by_scheduler(runtime, alice, project):
    handle = runtime.commands.create_video(
        alice,
        StudioCommand(
            project_id=project,
            idempotency_key="cancel-plan",
            input=BriefInput(brief="A calm product launch", duration_seconds=6),
        ),
    )
    runtime.worker.execute(project, handle.job_id)
    runtime.commands.cancel_run(alice, project, handle.run_id, "cancel-run")
    scheduler = WorkflowScheduler(runtime.commands)
    artifact = runtime.commands.get_job(alice, project, handle.job_id).artifact_ids[0]
    assert not scheduler.approval(project, handle.run_id, "storyboard", artifact)
    assert runtime.commands.get_run(alice, project, handle.run_id).status == "cancelled"
