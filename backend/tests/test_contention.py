from execution.dispatch import Reconciler
from tools.commands import project_path
from tools.contracts.studio import BriefInput, StudioCommand


def test_intermediate_workflow_steps_leave_the_shared_run_untouched(runtime, alice, project):
    handle = runtime.commands.create_video(
        alice,
        StudioCommand(project_id=project, idempotency_key="video", input=BriefInput(brief="A lamp launch")),
    )
    repo = runtime.commands.repo
    run_path = project_path(project, "runs", handle.run_id)
    before = repo.get(run_path)
    assert runtime.worker.claim(project, handle.job_id)
    assert repo.get(run_path) == before
    activity = repo.get(project_path(project, "run_summaries", handle.run_id + "_activity"))
    assert activity["status"] == "claimed"  # Studio listeners still see the step.
    runtime.worker.execute(project, handle.job_id)
    runtime.commands.clock.advance()  # The claim's lease expires; execute reclaims it.
    runtime.worker.execute(project, handle.job_id)
    assert repo.get(run_path)["version"] > before["version"]  # A finished job still updates its run.


def test_sweep_leaves_freshly_queued_jobs_to_their_dispatch(runtime, project, submit):
    job = submit()
    outbox = project_path(project, "outbox", job.job_id)
    before = runtime.commands.repo.get(outbox)
    assert Reconciler(runtime.commands).sweep() == 0
    assert runtime.commands.repo.get(outbox) == before
    runtime.commands.clock.advance(121)
    assert Reconciler(runtime.commands).sweep() == 1  # A dispatch lost for two minutes is recovered.


def test_concurrent_flushes_publish_each_row_once(runtime, project, submit):
    submit()
    sent = []

    class Reentrant:
        def publish(self, message):
            sent.append(message)
            # Another thread flushes the same project while this publish is in flight.
            runtime.commands.flush(project)

    runtime.commands.publisher = Reentrant()
    runtime.commands.flush(project)
    assert len(sent) == 1
