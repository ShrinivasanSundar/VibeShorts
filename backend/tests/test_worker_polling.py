from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import ResourceExhausted

from execution.dispatch import EmulatorPump
from tools.contracts.studio import ConversationCreate
from tools.conversations import ConversationScheduler, conversation_path


def test_idle_conversation_sweeps_do_not_write_leases(runtime, alice, project, monkeypatch):
    chat = runtime.commands.create_conversation(
        alice, project, ConversationCreate(idempotency_key="idle")
    ).data["id"]
    repo = runtime.commands.repo
    path = conversation_path(project, chat)
    repo.documents[path + "/messages/old"] = {"id": "old", "status": "succeeded"}
    before = deepcopy(repo.documents)
    atomic = Mock(side_effect=AssertionError("Idle chats must not start transactions"))
    monkeypatch.setattr(repo, "atomic", atomic)
    for _ in range(3):
        ConversationScheduler(runtime.commands).sweep()
    assert repo.documents == before
    atomic.assert_not_called()


def test_changed_run_still_synchronizes_without_pending_messages(runtime, alice, project, monkeypatch):
    chat = runtime.commands.create_conversation(
        alice, project, ConversationCreate(idempotency_key="sync")
    ).data["id"]
    repo = runtime.commands.repo
    path = conversation_path(project, chat)
    repo.documents[path].update(active_run_id="run", synced_run_id="run", synced_run_version=1)
    repo.documents[f"projects/{project}/runs/run"] = {"run_id": "run", "version": 2}
    repo.atomic(lambda tx: runtime.commands.project_run(tx, {"project_id": project, "run_id": "run", "version": 2, "conversation_id": chat, "workflow": {"stage": "production"}}))
    scheduler = ConversationScheduler(runtime.commands)
    advance = Mock()
    monkeypatch.setattr(scheduler, "advance", advance)
    scheduler.sweep()
    advance.assert_called_once()
    assert repo.get(path)["lease_expiry"] == 0


def test_local_worker_avoids_duplicate_sweep_and_uses_reduced_poll_rate(runtime, monkeypatch):
    runtime.commands.settings.local_live = True
    pump = EmulatorPump.__new__(EmulatorPump)
    pump.commands = runtime.commands
    pump.bootstrap = Mock()
    pump.reconciler = SimpleNamespace(sweep=Mock())
    pump.once = Mock()
    sleep = Mock(side_effect=InterruptedError)
    monkeypatch.setattr("execution.dispatch.time.sleep", sleep)
    with pytest.raises(InterruptedError):
        pump.run()
    pump.reconciler.sweep.assert_called_once()
    pump.once.assert_called_once_with(sweep_workflows=False)
    sleep.assert_called_once_with(30)


def test_worker_quota_log_includes_underlying_error(runtime, monkeypatch):
    pump = EmulatorPump.__new__(EmulatorPump)
    pump.commands = runtime.commands
    pump.bootstrap = Mock()
    pump.reconciler = SimpleNamespace(sweep=Mock(side_effect=ResourceExhausted("Firestore quota exceeded")))
    pump.once = Mock()
    log = Mock()
    monkeypatch.setattr("execution.dispatch.event", log)
    monkeypatch.setattr("execution.dispatch.time.sleep", Mock(side_effect=InterruptedError))
    with pytest.raises(InterruptedError):
        pump.run()
    fields = log.call_args.kwargs
    assert fields["operation"] == "reconcile"
    assert "Firestore quota exceeded" in fields["error"]
    assert fields["retry_after_seconds"] == 60
    pump.once.assert_not_called()
