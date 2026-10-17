import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import ResourceExhausted

from api.main import create_app
from execution.workflow import WorkflowScheduler
from tools.contracts.errors import AppError


def test_studio_reuses_loaded_jobs_and_limits_history(runtime, alice, bob, project, submit, monkeypatch):
    for i in range(65):
        submit(f"job-{i}")
        runtime.commands.clock.advance(1)
    reads = []
    original = runtime.commands.repo.get

    def read(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(runtime.commands.repo, "get", read)
    state = runtime.commands.studio_state(alice, project).data
    assert len(state["jobs"]) == 60
    assert len(state["runs"]) == 20
    assert len(state["events"]) <= 60
    assert not any("/jobs/" in path or "/runs/" in path for path in reads)
    assert all("caller" not in (run["workflow"] or {}) for run in state["runs"])
    with pytest.raises(AppError):
        runtime.commands.studio_state(bob, project)


def test_scheduler_does_not_touch_runs_waiting_for_approval(runtime, project, monkeypatch):
    repo = runtime.commands.repo
    repo.documents[f"projects/{project}/runs/paused"] = {
        "run_id": "paused",
        "status": "needs_approval",
        "workflow": {"stage": "preview"},
    }
    repo.documents[f"projects/{project}/runs/active"] = {
        "run_id": "active",
        "status": "waiting_for_jobs",
        "workflow": {"stage": "production"},
    }
    advanced = []
    scheduler = WorkflowScheduler(runtime.commands)
    monkeypatch.setattr(scheduler, "advance", lambda project, run: advanced.append(run))
    scheduler.sweep()
    assert advanced == ["active"]


def test_firestore_quota_returns_429_with_retry_after(runtime, monkeypatch):
    def exhausted(action):
        raise ResourceExhausted("Quota exceeded")

    monkeypatch.setattr(runtime.commands.repo, "atomic", exhausted)
    with TestClient(create_app(runtime)) as client:
        response = client.get("/v1/projects", headers={"Authorization": "Bearer alice"})
        assert response.status_code == 429
        assert response.json()["code"] == "FIRESTORE_QUOTA_EXHAUSTED"
        assert response.headers["Retry-After"] == "60"
        assert client.get("/v1/projects").status_code == 401
