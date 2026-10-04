from concurrent.futures import ThreadPoolExecutor

from providers.image import FixtureImageProvider
from tools.contracts.errors import AppError
from tools.contracts.models import ImageCommand, ImageInput, ProjectCreate


class PaidFixture(FixtureImageProvider):
    def snapshot(self):
        return {**super().snapshot(), "route": "vertex"}


def test_shared_account_allowance_cannot_be_replenished_with_new_projects(runtime, alice):
    commands = runtime.commands
    # Explicit injected test provider simulates paid accounting without cloud calls.
    commands.provider = PaidFixture()
    commands.settings.provider = "vertex"
    commands.settings.paid_allowance_micros = 1000
    projects = [
        commands.create_project(alice, ProjectCreate(name=f"Project {i}", idempotency_key=str(i))).data[
            "project_id"
        ]
        for i in range(2)
    ]

    def submit(project):
        try:
            return commands.generate_image(
                alice,
                ImageCommand(project_id=project, idempotency_key="image", input=ImageInput(prompt="Launch")),
            )
        except AppError as exc:
            return exc.payload.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, projects))
    assert results.count("BUDGET_EXHAUSTED") == 1
    accepted = next(r for r in results if r != "BUDGET_EXHAUSTED")
    project = projects[results.index(accepted)]
    assert commands.repo.get("budgets/account")["reserved_micros"] == 1000
    runtime.worker.execute(project, accepted.job_id)
    assert commands.repo.get("budgets/account")["settled_micros"] == 1000
    assert commands.repo.get("budgets/account")["reserved_micros"] == 0
    fresh = commands.create_project(alice, ProjectCreate(name="Fresh", idempotency_key="fresh")).data[
        "project_id"
    ]
    assert submit(fresh) == "BUDGET_EXHAUSTED"


def test_cancelling_before_submission_releases_shared_allowance(runtime, alice):
    commands = runtime.commands
    commands.provider = PaidFixture()
    commands.settings.provider = "vertex"
    commands.settings.paid_allowance_micros = 1000
    project = commands.create_project(alice, ProjectCreate(name="Project", idempotency_key="p")).data[
        "project_id"
    ]
    job = commands.generate_image(
        alice, ImageCommand(project_id=project, idempotency_key="first", input=ImageInput(prompt="Launch"))
    )
    commands.cancel_job(alice, project, job.job_id, "cancel")
    assert commands.repo.get("budgets/account")["reserved_micros"] == 0
    assert commands.generate_image(
        alice, ImageCommand(project_id=project, idempotency_key="second", input=ImageInput(prompt="Launch"))
    )
