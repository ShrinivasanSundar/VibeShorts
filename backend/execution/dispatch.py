import json
import threading
import time

from execution.telemetry import event
from tools.commands import project_path
from tools.contracts.errors import AppError

# A queued job is recovered only after this long, so the sweep does not duplicate live dispatches.
QUEUED_GRACE_SECONDS = 120


def live_matches(repo, group, field, values):
    """(project_id, document) pairs from one collection-group query, skipping deleting projects."""
    matches = [(path.split("/")[1], doc) for path, doc in repo.group_where(group, field, values)]
    ids = list(dict.fromkeys(pid for pid, _ in matches))
    projects = repo.get_many([project_path(i) for i in ids])
    live = {pid for pid, p in zip(ids, projects, strict=True) if p and not p.get("deleting")}
    return [(pid, doc) for pid, doc in matches if pid in live]


class PubSubPublisher:
    def __init__(self, settings):
        from google.cloud import pubsub_v1

        self.client = pubsub_v1.PublisherClient()
        self.topic = self.client.topic_path(settings.google_cloud_project, settings.topic)

    def publish(self, message):
        self.client.publish(self.topic, json.dumps(message).encode()).result(timeout=30)


class RecentlyPublished:
    """Outbox row versions this process already sent, so concurrent flushes publish each once.

    Another process may still send a duplicate; job leases and scheduler leases absorb it.
    """

    def __init__(self, ttl_seconds=120):
        self.ttl, self.sent, self.lock = ttl_seconds, {}, threading.Lock()

    def reserve(self, key):
        now = time.monotonic()
        with self.lock:
            for old in [k for k, at in self.sent.items() if now - at > self.ttl]:
                del self.sent[old]
            if key in self.sent:
                return False
            self.sent[key] = now
            return True

    def release(self, key):
        with self.lock:
            self.sent.pop(key, None)


class Dispatcher:
    def __init__(self, commands, publisher, recent=None):
        self.commands, self.publisher, self.recent = commands, publisher, recent

    def dispatch(self, project_id=None):
        """Publish due outbox rows: every project's, or one project's after it committed new work."""
        repo = self.commands.repo
        if project_id is None:
            items = live_matches(repo, "outbox", "status", ["pending"])
        else:
            project = repo.get(project_path(project_id))
            if not project or project.get("deleting"):
                return 0
            pending = repo.list_where(project_path(project_id, "outbox"), "status", ["pending"])
            items = [(project_id, item) for item in pending]
        sent = 0
        for project_id, item in items:
            if item["status"] != "pending" or item["next_attempt_at"] > self.commands.clock():
                continue
            fields = (
                {"kind": "advance", "target": item["target"], "target_id": item["target_id"]}
                if item.get("kind") == "advance"
                else {"job_id": item["job_id"]}
            )
            key = (project_id, item["id"], item["next_attempt_at"], item.get("nonce"))
            if self.recent and not self.recent.reserve(key):
                continue  # Another thread of this process is sending, or already sent, this row.
            published = False
            try:
                self.publisher.publish({"project_id": project_id, **fields})
                published = True

                def mark(tx, project_id=project_id, item=item):
                    path = project_path(project_id, "outbox", item["id"])
                    current = tx.get(path)
                    if (
                        current
                        and current["status"] == "pending"
                        and current["next_attempt_at"] == item["next_attempt_at"]
                        and current.get("nonce") == item.get("nonce")
                    ):
                        current["status"] = "sent"
                        tx.set(path, current)

                self.commands.repo.atomic(mark)
                sent += 1
                event(
                    "outbox_sent",
                    **fields,
                    queue_age_seconds=self.commands.clock() - item["created_at"],
                )
            except Exception:
                if self.recent and not published:
                    self.recent.release(key)

                def retry(tx, project_id=project_id, item=item):
                    path = project_path(project_id, "outbox", item["id"])
                    current = tx.get(path)
                    if current and current["status"] == "pending":
                        current["attempts"] += 1
                        current["next_attempt_at"] = self.commands.clock() + min(
                            60, 2 ** min(current["attempts"], 6)
                        )
                        tx.set(path, current)

                self.commands.repo.atomic(retry)
                event("outbox_failure", **fields)
        return sent


def advance(commands, project_id, target, target_id):
    """One scheduler pass for a run or conversation. False means another pass holds its lease."""
    from execution.workflow import WorkflowScheduler
    from tools.conversations import ConversationScheduler, conversation_path

    project = commands.repo.get(project_path(project_id))
    if not project or project.get("deleting"):
        return True
    if target == "run":
        run = commands.repo.get(project_path(project_id, "runs", target_id))
        return WorkflowScheduler(commands).resume(project_id, run) if run else True
    doc = commands.repo.get(conversation_path(project_id, target_id))
    if not doc or doc.get("deleting"):
        return True
    return ConversationScheduler(commands).resume(project_id, doc)


def handle(commands, worker, message):
    """Process one queue message, then publish the work it enqueued without waiting for a sweep."""
    project_id = message["project_id"]
    try:
        if message.get("kind") == "advance":
            if not advance(commands, project_id, message["target"], message["target_id"]):
                # Another pass may have read state before this change; redelivery runs a fresh pass.
                raise AppError("SCHEDULER_BUSY", "Another scheduler pass is in progress", 409, retryable=True)
        else:
            worker.execute(project_id, message["job_id"])
    finally:
        commands.flush(project_id)


class Reconciler:
    def __init__(self, commands):
        self.commands = commands

    def sweep(self):
        from execution.workflow import WorkflowScheduler

        WorkflowScheduler(self.commands).sweep()
        recovered = 0
        statuses = [
            "queued",
            "claimed",
            "submitting",
            "waiting_for_provider",
            "cancel_requested",
            "submission_unknown",
            "materializing",
        ]
        for project_id, job in live_matches(self.commands.repo, "jobs", "status", statuses):
            if job["status"] in {"succeeded", "failed", "cancelled"}:
                continue
            if job["lease_owner"] and job["lease_expires_at"] > self.commands.clock():
                continue
            if (
                job["status"] == "queued"
                and self.commands.clock() - job.get("updated_at", 0) < QUEUED_GRACE_SECONDS
            ):
                continue  # Its dispatch is likely in flight; re-queueing now only publishes a duplicate.
            candidate = self.commands.storage.get(job["candidate_path"]) if job["candidate_path"] else None
            from execution.director_recovery import recover_director_failure

            if not candidate and recover_director_failure(self.commands, job):
                recovered += 1
                continue

            def apply(tx, project_id=project_id, job=job, candidate=candidate):
                current = tx.get(project_path(project_id, "jobs", job["job_id"]))
                if (
                    not current
                    or current["status"] in {"succeeded", "failed", "cancelled"}
                    or current["lease_expires_at"] > self.commands.clock()
                ):
                    return False
                current["lease_owner"], current["lease_expires_at"] = None, 0
                if current.get("provider_operation") and not candidate:
                    self.commands.transition(tx, current, "waiting_for_provider")
                    current["next_poll_at"] = self.commands.clock()
                    tx.set(project_path(project_id, "jobs", current["job_id"]), current)
                    tx.set(
                        project_path(project_id, "outbox", current["job_id"]),
                        {
                            "id": current["job_id"],
                            "job_id": current["job_id"],
                            "project_id": project_id,
                            "status": "pending",
                            "next_attempt_at": self.commands.clock(),
                            "attempts": 0,
                            "created_at": self.commands.clock(),
                        },
                    )
                    return True
                if current["status"] in {
                    "submitting",
                    "cancel_requested",
                    "submission_unknown",
                    "materializing",
                }:
                    if (
                        candidate
                        and candidate[1].get("input_hash") == current["input_hash"]
                        and candidate[1].get("attempt") == current["attempt"]
                        and current["candidate_path"] == job["candidate_path"]
                    ):
                        self.commands.transition(tx, current, "materializing")
                    else:
                        if current["status"] == "submission_unknown":
                            return False
                        current["costs"]["uncertain"] = True
                        entry_path = "budgets/" + project_id + "/entries/" + job["job_id"]
                        entry = tx.get(entry_path)
                        entry.update(status="uncertain", uncertain=True)
                        tx.set(entry_path, entry)
                        current["error"] = AppError(
                            "PROVIDER_SUBMISSION_UNCERTAIN",
                            "The provider may have accepted this request",
                            action="reconcile",
                            job_id=job["job_id"],
                        ).payload.model_dump()
                        self.commands.transition(tx, current, "submission_unknown")
                        event("uncertain_submission", job_id=job["job_id"])
                        return True
                else:
                    self.commands.transition(tx, current, "queued")
                tx.set(
                    project_path(project_id, "outbox", job["job_id"]),
                    {
                        "id": job["job_id"],
                        "job_id": job["job_id"],
                        "project_id": project_id,
                        "status": "pending",
                        "next_attempt_at": self.commands.clock(),
                        "attempts": 0,
                        "created_at": self.commands.clock(),
                    },
                )
                event("lease_recovered", job_id=job["job_id"])
                return True

            recovered += int(self.commands.repo.atomic(apply))
        return recovered


class EmulatorPump:
    """A local dispatcher/subscriber; Firestore and Pub/Sub still own durable work."""

    # Jobs handled at once. Each may hold an FFmpeg process or a 4 GB Docker render.
    CONCURRENCY = 6

    def __init__(self, commands, worker):
        from google.cloud import pubsub_v1

        self.commands, self.worker = commands, worker
        self.publisher = PubSubPublisher(commands.settings)
        commands.publisher = self.publisher
        self.subscriber = pubsub_v1.SubscriberClient()
        self.subscription = self.subscriber.subscription_path(
            commands.settings.google_cloud_project,
            "vibeshorts-local-live" if commands.settings.local_live else "vibeshorts-local",
        )
        self.dispatcher = Dispatcher(commands, self.publisher, commands.recently_published)
        self.reconciler = Reconciler(commands)

    def bootstrap(self):
        from google.api_core.exceptions import AlreadyExists

        try:
            self.publisher.client.create_topic(request={"name": self.publisher.topic})
        except AlreadyExists:
            pass
        try:
            self.subscriber.create_subscription(
                request={"name": self.subscription, "topic": self.publisher.topic}
            )
        except AlreadyExists:
            pass

    def once(self, *, sweep_workflows=True, dispatch=True, wait=True):
        from execution.workflow import WorkflowScheduler

        if sweep_workflows:
            WorkflowScheduler(self.commands).sweep()
        from google.api_core.exceptions import DeadlineExceeded

        if dispatch:
            self.dispatcher.dispatch()
        # Jobs run concurrently, as Cloud Run push delivery does; leases fence duplicate work.
        if getattr(self, "pool", None) is None:
            from concurrent.futures import ThreadPoolExecutor

            self.pool = ThreadPoolExecutor(max_workers=self.CONCURRENCY, thread_name_prefix="vibeshorts-job")
            self.in_flight = set()
        self.in_flight = {future for future in self.in_flight if not future.done()}
        free = self.CONCURRENCY - len(self.in_flight)
        if free <= 0:
            return
        try:
            response = self.subscriber.pull(
                request={"subscription": self.subscription, "max_messages": min(10, free)}, timeout=2
            )
        except DeadlineExceeded:
            return
        messages = list(response.received_messages)
        if not messages:
            return
        # Long steps (composition, renders) outlast the subscription's default ack deadline.
        self._ack_deadline([m.ack_id for m in messages], 600)
        futures = [self.pool.submit(self._process, message) for message in messages]
        self.in_flight.update(futures)
        if wait:
            for future in futures:
                future.result()

    def _ack_deadline(self, ack_ids, seconds):
        self.subscriber.modify_ack_deadline(
            request={"subscription": self.subscription, "ack_ids": ack_ids, "ack_deadline_seconds": seconds}
        )

    def _process(self, message):
        try:
            handle(self.commands, self.worker, json.loads(message.message.data))
        except Exception as exc:
            busy = isinstance(exc, AppError) and exc.payload.code == "SCHEDULER_BUSY"
            if not busy:
                event("worker_message_failed", exception_type=type(exc).__name__, error=str(exc)[-500:])
            # Unacknowledged with a short deadline: redelivered soon without spinning.
            self._ack_deadline([message.ack_id], 10 if busy else 30)
            if not busy:
                raise
            return
        self.subscriber.acknowledge(request={"subscription": self.subscription, "ack_ids": [message.ack_id]})

    def run(self):
        self.bootstrap()
        next_sweep = next_scan = 0
        # Handled messages publish their follow-up work, so the Firestore scans are a fallback
        # at the configured rate while Pub/Sub pulls continue between them.
        settings = self.commands.settings
        interval = settings.local_live_poll_seconds if settings.local_live else 0.25
        while True:
            from google.api_core.exceptions import ResourceExhausted

            try:
                reconciled = False
                operation = "reconcile"
                if time.time() >= next_sweep:
                    self.reconciler.sweep()
                    next_sweep = time.time() + 60
                    reconciled = True
                operation = "dispatch_and_execute"
                scan = time.time() >= next_scan
                if scan:
                    next_scan = time.time() + interval
                # Locally against live Firestore, the minute reconcile already sweeps workflows.
                sweep_workflows = scan and not reconciled and not settings.local_live
                # Pulling continues while earlier jobs run, up to the pool's capacity.
                self.once(sweep_workflows=sweep_workflows, dispatch=scan, wait=False)
            except ResourceExhausted as exc:
                event("worker_quota_exhausted", operation=operation, error=str(exc), retry_after_seconds=60)
                time.sleep(60)
                continue
            time.sleep(0.25)


def reconcile_decision(commands, project_id, job_id, amount_micros, evidence, operator):
    if amount_micros < 0 or not evidence.strip() or not operator.strip():
        raise AppError("INVALID_INPUT", "A nonnegative charge, operator and evidence are required")

    def apply(tx):
        job = tx.get(project_path(project_id, "jobs", job_id))
        if not job or job["status"] != "submission_unknown":
            raise AppError("REVISION_CONFLICT", "Job is not awaiting reconciliation", 409)
        commands.settle(tx, job, amount_micros, "operator_billing_evidence", {})
        tx.set(
            project_path(project_id, "reconciliations", job_id),
            {
                "job_id": job_id,
                "operator": operator,
                "evidence": evidence,
                "amount_micros": amount_micros,
                "created_at": commands.clock(),
            },
        )
        job["error"] = AppError(
            "RECONCILED_WITHOUT_OUTPUT",
            "Submission reconciled without a usable image",
            action="submit_new_request",
        ).payload.model_dump()
        commands.transition(tx, job, "cancelled" if job["cancel_requested"] else "failed")

    commands.repo.atomic(apply)


def revoke_access(commands, uid):
    # Gate immediately even if the subsequent Firebase revocation call fails.
    def disable(tx):
        user = tx.get("users/" + uid)
        if not user:
            raise AppError("NOT_FOUND", "User not provisioned", 404)
        user["access_enabled"] = False
        user["access_version"] += 1
        tx.set("users/" + uid, user)

    commands.repo.atomic(disable)
    for grant in commands.repo.list("oauth_grants"):
        if grant["uid"] == uid:
            commands.repo.atomic(
                lambda tx, grant=grant: tx.set("oauth_grants/" + grant["id"], {**grant, "revoked": True})
            )
    for project in commands.repo.list("projects"):
        if not project.get("project_id"):
            continue
        for job in commands.repo.list(project_path(project["project_id"], "jobs")):
            if job["caller"]["uid"] == uid and job["status"] not in {"succeeded", "failed", "cancelled"}:

                def cancel(tx, job=job):
                    current = tx.get(project_path(job["project_id"], "jobs", job["job_id"]))
                    current["cancel_requested"] = True
                    commands.transition(tx, current, current["status"])

                commands.repo.atomic(cancel)
    commands.identity.revoke(uid)
