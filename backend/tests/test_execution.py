from concurrent.futures import ThreadPoolExecutor

import pytest

from execution.dispatch import Dispatcher, Reconciler, reconcile_decision, revoke_access
from execution.storage import inspect_image
from providers.image import ProviderFailure
from tools.commands import project_path
from tools.contracts.errors import AppError
from tools.contracts.models import BrandInput, BrandUpdate, ImageCommand, ImageInput, ProjectCreate


def test_complete_image_is_private_immutable_and_settled_once(runtime, alice, project, submit):
    job = submit()
    assert runtime.worker.execute(project, job.job_id)
    result = runtime.commands.get_job(alice, project, job.job_id)
    assert result.status == "succeeded"
    assert result.costs["reserved_micros"] == 0
    assert result.costs["settled_micros"] == 1000
    asset = runtime.commands.get_asset(alice, project, result.artifact_ids[0]).data
    assert "storage_uri" not in asset
    assert asset["requires_authorization"]
    data, mime = runtime.commands.asset_content(alice, project, result.artifact_ids[0])
    assert inspect_image(data, mime)["content_sha256"] == asset["content_sha256"]
    assert not runtime.worker.execute(project, job.job_id)
    assert runtime.commands.provider.calls == 1
    assert runtime.commands.repo.get("budgets/" + project)["settled_micros"] == 1000
    run = runtime.commands.get_run(alice, project, job.run_id)
    assert run.status == "succeeded"
    assert run.active_steps[0]["status"] == "succeeded"


def test_idempotency_replay_and_conflicting_input(runtime, alice, project, submit):
    first = submit()
    assert submit().job_id == first.job_id
    with pytest.raises(AppError, match="different input"):
        submit(aspect_ratio="16:9")
    assert len(runtime.commands.repo.list(project_path(project, "jobs"))) == 1
    assert runtime.commands.repo.get("budgets/" + project)["reserved_micros"] == 1000


def test_concurrent_reservations_cannot_spend_same_balance(runtime, alice, project, submit):
    runtime.commands.repo.atomic(
        lambda tx: tx.set(
            "budgets/" + project,
            {"cap_micros": 1000, "reserved_micros": 0, "settled_micros": 0, "currency": "USD"},
        )
    )

    def attempt(i):
        try:
            return submit(str(i)).job_id
        except AppError as exc:
            return exc.payload.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert results.count("BUDGET_EXHAUSTED") == 7
    assert len(runtime.commands.repo.list(project_path(project, "jobs"))) == 1


def test_run_cap_only_lowers_allowance(runtime, submit):
    with pytest.raises(AppError) as exc:
        submit(spend_cap_micros=999)
    assert exc.value.payload.code == "BUDGET_EXHAUSTED"


def test_crash_before_publish_recovers_outbox_and_duplicate_dispatch(runtime, project, submit):
    job = submit()

    class Queue:
        def __init__(self):
            self.messages = []

        def publish(self, message):
            self.messages.append(message)

    queue = Queue()
    dispatcher = Dispatcher(runtime.commands, queue)
    assert dispatcher.dispatch() == 1
    # Crash after successful publish, before sent marker: message is sent twice.
    path = project_path(project, "outbox", job.job_id)
    runtime.commands.repo.atomic(lambda tx: tx.set(path, {**tx.get(path), "status": "pending"}))
    assert dispatcher.dispatch() == 1
    for message in queue.messages:
        runtime.worker.execute(**message)
    assert runtime.commands.provider.calls == 1


def test_expired_pre_submission_claim_can_be_reclaimed(runtime, project, submit):
    job = submit()
    claimed = runtime.worker.claim(project, job.job_id)
    assert not runtime.worker.claim(project, job.job_id)
    runtime.commands.clock.advance()
    assert Reconciler(runtime.commands).sweep() == 1
    runtime.worker.execute(project, job.job_id)
    assert runtime.commands.provider.calls == 1
    assert (
        runtime.commands.repo.get(project_path(project, "jobs", job.job_id))["generation"]
        > claimed["generation"]
    )


def test_crash_after_paid_request_retains_liability_and_never_regenerates(runtime, project, submit):
    class ProcessDied(BaseException):
        pass

    def crash(*args):
        runtime.commands.provider.calls += 1
        raise ProcessDied()

    runtime.commands.provider.generate = crash
    job = submit()
    with pytest.raises(ProcessDied):
        runtime.worker.execute(project, job.job_id)
    runtime.commands.clock.advance()
    Reconciler(runtime.commands).sweep()
    current = runtime.commands.repo.get(project_path(project, "jobs", job.job_id))
    assert current["status"] == "submission_unknown"
    assert current["costs"]["reserved_micros"] == 1000
    assert current["costs"]["uncertain"]
    assert not runtime.worker.execute(project, job.job_id)
    Reconciler(runtime.commands).sweep()
    assert runtime.commands.provider.calls == 1
    assert (
        runtime.commands.repo.get(project_path(project, "runs", job.run_id))["status"]
        == "needs_reconciliation"
    )


def test_crash_after_upload_recovers_bytes_without_provider_call(runtime, alice, project, submit):
    class ProcessDied(BaseException):
        pass

    put = runtime.commands.storage.put

    def crash_after_upload(*args):
        put(*args)
        raise ProcessDied()

    runtime.commands.storage.put = crash_after_upload
    job = submit()
    with pytest.raises(ProcessDied):
        runtime.worker.execute(project, job.job_id)
    runtime.commands.clock.advance()
    Reconciler(runtime.commands).sweep()
    runtime.worker.execute(project, job.job_id)
    assert runtime.commands.get_job(alice, project, job.job_id).status == "succeeded"
    assert runtime.commands.provider.calls == 1


def test_stale_worker_cannot_publish(runtime, alice, project, submit):
    original = runtime.commands.provider.generate

    def slow(*args):
        output = original(*args)
        runtime.commands.clock.advance()
        Reconciler(runtime.commands).sweep()
        return output

    runtime.commands.provider.generate = slow
    job = submit()
    runtime.worker.execute(project, job.job_id)
    assert runtime.commands.get_job(alice, project, job.job_id).status == "submission_unknown"
    assert runtime.commands.list_assets(alice, project).assets == []
    Reconciler(runtime.commands).sweep()
    runtime.worker.execute(project, job.job_id)
    assert runtime.commands.provider.calls == 1
    assert runtime.commands.get_job(alice, project, job.job_id).status == "succeeded"


@pytest.mark.parametrize("timing", ["queued", "during_provider"])
def test_cancellation_respects_accepted_cost(runtime, alice, project, submit, timing):
    job = submit()
    if timing == "queued":
        runtime.commands.cancel_job(alice, project, job.job_id, "cancel")
        runtime.worker.execute(project, job.job_id)
        expected_cost, expected_calls = 0, 0
    else:
        original = runtime.commands.provider.generate

        def cancel(*args):
            runtime.commands.cancel_job(alice, project, job.job_id, "cancel")
            return original(*args)

        runtime.commands.provider.generate = cancel
        runtime.worker.execute(project, job.job_id)
        expected_cost, expected_calls = 1000, 1
    result = runtime.commands.get_job(alice, project, job.job_id)
    assert result.status == "cancelled"
    assert result.costs["settled_micros"] == expected_cost
    assert not result.artifact_ids
    assert runtime.commands.provider.calls == expected_calls


def test_permission_removed_before_worker_prevents_provider_call(runtime, alice, project, submit):
    job = submit()
    path = project_path(project)
    runtime.commands.repo.atomic(lambda tx: tx.set(path, {**tx.get(path), "members": {}}))
    runtime.worker.execute(project, job.job_id)
    assert runtime.commands.provider.calls == 0
    assert runtime.commands.repo.get(project_path(project, "jobs", job.job_id))["status"] == "cancelled"


@pytest.mark.parametrize(
    "code,uncertain",
    [("SAFETY_REJECTED", False), ("PROVIDER_UNAVAILABLE", False), ("PROVIDER_SUBMISSION_UNCERTAIN", True)],
)
def test_provider_failures_are_typed_and_not_retried(runtime, alice, project, submit, code, uncertain):
    def reject(*args):
        runtime.commands.provider.calls += 1
        raise ProviderFailure(code, "Rejected", uncertain=uncertain)

    runtime.commands.provider.generate = reject
    job = submit()
    runtime.worker.execute(project, job.job_id)
    assert not runtime.worker.execute(project, job.job_id)
    result = runtime.commands.get_job(alice, project, job.job_id)
    assert result.status == ("submission_unknown" if uncertain else "failed")
    assert result.error.code == code
    assert runtime.commands.provider.calls == 1


def test_operator_reconciliation_closes_uncertainty_without_resubmission(runtime, project, submit):
    def fail(*args):
        raise ProviderFailure("PROVIDER_SUBMISSION_UNCERTAIN", "Unknown", uncertain=True)

    runtime.commands.provider.generate = fail
    job = submit()
    runtime.worker.execute(project, job.job_id)
    reconcile_decision(
        runtime.commands, project, job.job_id, 600, "Billing report operation XYZ", "operator@example"
    )
    current = runtime.commands.repo.get(project_path(project, "jobs", job.job_id))
    assert current["status"] == "failed"
    assert current["costs"]["settled_micros"] == 600
    assert current["costs"]["reserved_micros"] == 0
    with pytest.raises(AppError):
        reconcile_decision(runtime.commands, project, job.job_id, 0, "Repeat", "operator")


def test_cross_project_and_scope_denied_before_reservation(runtime, alice, bob, project):
    with pytest.raises(AppError) as exc:
        runtime.commands.generate_image(
            bob,
            ImageCommand(
                project_id=project,
                idempotency_key="forged",
                input=ImageInput(prompt="Another project's image"),
            ),
        )
    assert exc.value.status == 403
    assert runtime.commands.repo.list(project_path(project, "jobs")) == []
    with pytest.raises(AppError):
        runtime.commands.get_project_context(alice, "../../users/alice")


def test_brand_versions_are_immutable_and_snapshotted(runtime, alice, project, submit):
    first = runtime.commands.update_brand(
        alice,
        project,
        BrandUpdate(
            idempotency_key="brand-1", expected_version=0, brand=BrandInput(colors={"primary": "#2864FF"})
        ),
    ).data
    job = submit()
    runtime.commands.update_brand(
        alice,
        project,
        BrandUpdate(
            idempotency_key="brand-2", expected_version=1, brand=BrandInput(colors={"primary": "#FFFFFF"})
        ),
    )
    assert runtime.commands.get_brand_dna(alice, project, 1).data == first
    assert runtime.commands.get_run(alice, project, job.run_id).brand_version == "brand_1"
    with pytest.raises(AppError) as exc:
        runtime.commands.update_brand(
            alice, project, BrandUpdate(idempotency_key="stale", expected_version=0, brand=BrandInput())
        )
    assert exc.value.payload.code == "REVISION_CONFLICT"


def test_revocation_gates_requests_and_pending_work(runtime, alice, project, submit):
    job = submit()
    revoke_access(runtime.commands, "alice")
    with pytest.raises(AppError):
        runtime.commands.get_job(alice, project, job.job_id)
    runtime.worker.execute(project, job.job_id)
    assert runtime.commands.provider.calls == 0


def test_new_user_cannot_join_existing_projects(runtime, alice, bob, project):
    created = runtime.commands.create_project(bob, ProjectCreate(name="Bob", idempotency_key="bob"))
    assert created.data["project_id"] != project
    assert [p["project_id"] for p in runtime.commands.list_projects(bob).data["projects"]] == [
        created.data["project_id"]
    ]
