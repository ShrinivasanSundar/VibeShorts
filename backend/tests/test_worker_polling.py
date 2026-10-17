import json
import threading
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from google.api_core.exceptions import ResourceExhausted

from execution.dispatch import EmulatorPump
from tools.contracts.errors import AppError
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
    repo.documents[f"projects/{project}/runs/run"] = {
        "run_id": "run",
        "version": 2,
        "status": "waiting_for_jobs",
        "conversation_id": chat,
    }
    scheduler = ConversationScheduler(runtime.commands)
    advance = Mock()
    monkeypatch.setattr(scheduler, "advance", advance)
    scheduler.sweep()
    advance.assert_called_once()
    assert repo.get(path)["lease_expiry"] == 0


def test_sweep_does_not_scan_idle_projects_or_conversations(runtime, alice, project, monkeypatch):
    for key in ("a", "b", "c"):
        runtime.commands.create_conversation(alice, project, ConversationCreate(idempotency_key=key))
    repo = runtime.commands.repo
    listed = Mock(side_effect=AssertionError("The sweep must use status queries, not collection scans"))
    monkeypatch.setattr(repo, "list", listed)
    ConversationScheduler(runtime.commands).sweep()
    listed.assert_not_called()


def test_local_worker_avoids_duplicate_sweep_and_uses_reduced_poll_rate(runtime, monkeypatch):
    runtime.commands.settings.local_live = True
    pump = EmulatorPump.__new__(EmulatorPump)
    pump.commands = runtime.commands
    pump.bootstrap = Mock()
    pump.reconciler = SimpleNamespace(sweep=Mock())
    pump.once = Mock()
    sleep = Mock(side_effect=[None, InterruptedError])
    monkeypatch.setattr("execution.dispatch.time.sleep", sleep)
    monkeypatch.setattr("execution.dispatch.time.time", Mock(return_value=1000.0))
    with pytest.raises(InterruptedError):
        pump.run()
    pump.reconciler.sweep.assert_called_once()
    # Firestore scans run at the reduced rate; Pub/Sub pulls continue between them.
    assert pump.once.call_args_list == [
        call(sweep_workflows=False, dispatch=True, wait=False),
        call(sweep_workflows=False, dispatch=False, wait=False),
    ]
    assert sleep.call_args_list == [call(0.25), call(0.25)]


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


def pump_with(runtime, messages):
    pump = EmulatorPump.__new__(EmulatorPump)
    pump.commands, pump.worker, pump.subscription = runtime.commands, Mock(), "sub"
    pump.dispatcher = SimpleNamespace(dispatch=Mock())
    received = [
        SimpleNamespace(ack_id=f"ack-{i}", message=SimpleNamespace(data=json.dumps(body).encode()))
        for i, body in enumerate(messages)
    ]
    pump.subscriber = Mock()
    pump.subscriber.pull.return_value = SimpleNamespace(received_messages=received)
    return pump


def test_pulled_jobs_run_concurrently_and_are_acknowledged(runtime, monkeypatch):
    count = 4
    barrier = threading.Barrier(count, timeout=5)
    monkeypatch.setattr("execution.dispatch.handle", lambda commands, worker, message: barrier.wait())
    pump = pump_with(runtime, [{"project_id": "p", "job_id": f"job_{i}"} for i in range(count)])
    # A sequential worker would deadlock on the barrier and raise BrokenBarrierError.
    pump.once(sweep_workflows=False)
    acked = {c.kwargs["request"]["ack_ids"][0] for c in pump.subscriber.acknowledge.call_args_list}
    assert acked == {f"ack-{i}" for i in range(count)}
    extended = pump.subscriber.modify_ack_deadline.call_args.kwargs["request"]
    assert extended["ack_deadline_seconds"] == 600


def test_busy_and_failed_messages_are_left_for_redelivery(runtime, monkeypatch):
    def fail(commands, worker, message):
        if message["job_id"] == "busy":
            raise AppError("SCHEDULER_BUSY", "Another pass", 409)
        raise RuntimeError("provider down")

    monkeypatch.setattr("execution.dispatch.handle", fail)
    pump = pump_with(runtime, [{"project_id": "p", "job_id": "busy"}, {"project_id": "p", "job_id": "x"}])
    pump.once(sweep_workflows=False, wait=False)
    for future in list(pump.in_flight):
        future.exception(timeout=5)
    pump.subscriber.acknowledge.assert_not_called()
    calls = pump.subscriber.modify_ack_deadline.call_args_list
    deadlines = sorted(c.kwargs["request"]["ack_deadline_seconds"] for c in calls)
    assert deadlines == [10, 30, 600]
