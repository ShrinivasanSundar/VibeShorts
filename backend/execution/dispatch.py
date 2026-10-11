import json
import time

from execution.telemetry import event
from tools.commands import project_path
from tools.contracts.errors import AppError


class PubSubPublisher:
    def __init__(self, settings):
        from google.cloud import pubsub_v1

        self.client = pubsub_v1.PublisherClient()
        self.topic = self.client.topic_path(settings.google_cloud_project, settings.topic)

    def publish(self, message):
        self.client.publish(self.topic, json.dumps(message).encode()).result(timeout=30)


class Dispatcher:
    def __init__(self, commands, publisher):
        self.commands, self.publisher = commands, publisher

    def dispatch(self):
        sent = 0
        for project in self.commands.repo.list("projects"):
            if not project.get("project_id"):
                continue
            project_id = project["project_id"]
            for item in self.commands.repo.list(project_path(project_id, "outbox")):
                if item["status"] != "pending" or item["next_attempt_at"] > self.commands.clock():
                    continue
                try:
                    self.publisher.publish({"project_id": project_id, "job_id": item["job_id"]})

                    def mark(tx, project_id=project_id, item=item):
                        path = project_path(project_id, "outbox", item["id"])
                        current = tx.get(path)
                        if (
                            current
                            and current["status"] == "pending"
                            and current["next_attempt_at"] == item["next_attempt_at"]
                        ):
                            current["status"] = "sent"
                            tx.set(path, current)

                    self.commands.repo.atomic(mark)
                    sent += 1
                    event(
                        "outbox_sent",
                        job_id=item["job_id"],
                        queue_age_seconds=self.commands.clock() - item["created_at"],
                    )
                except Exception:

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
                    event("outbox_failure", job_id=item["job_id"])
        return sent


class Reconciler:
    def __init__(self, commands):
        self.commands = commands

    def sweep(self):
        from execution.workflow import WorkflowScheduler

        WorkflowScheduler(self.commands).sweep()
        recovered = 0
        for project in self.commands.repo.list("projects"):
            if not project.get("project_id"):
                continue
            project_id = project["project_id"]
            for job in self.commands.repo.list(project_path(project_id, "jobs")):
                if job["status"] in {"succeeded", "failed", "cancelled"}:
                    continue
                if job["lease_owner"] and job["lease_expires_at"] > self.commands.clock():
                    continue
                candidate = (
                    self.commands.storage.get(job["candidate_path"]) if job["candidate_path"] else None
                )

                def apply(tx, project_id=project_id, job=job, candidate=candidate):
                    current = tx.get(project_path(project_id, "jobs", job["job_id"]))
                    if (
                        current["status"] in {"succeeded", "failed", "cancelled"}
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

    def __init__(self, commands, worker):
        from google.cloud import pubsub_v1

        self.commands, self.worker = commands, worker
        self.publisher = PubSubPublisher(commands.settings)
        self.subscriber = pubsub_v1.SubscriberClient()
        self.subscription = self.subscriber.subscription_path(
            commands.settings.google_cloud_project,
            "vibeshorts-local-live" if commands.settings.local_live else "vibeshorts-local",
        )
        self.dispatcher = Dispatcher(commands, self.publisher)
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

    def once(self):
        from execution.workflow import WorkflowScheduler

        WorkflowScheduler(self.commands).sweep()
        from google.api_core.exceptions import DeadlineExceeded

        self.dispatcher.dispatch()
        try:
            response = self.subscriber.pull(
                request={"subscription": self.subscription, "max_messages": 10}, timeout=2
            )
        except DeadlineExceeded:
            return
        for message in response.received_messages:
            body = json.loads(message.message.data)
            self.worker.execute(body["project_id"], body["job_id"])
            self.subscriber.acknowledge(
                request={"subscription": self.subscription, "ack_ids": [message.ack_id]}
            )

    def run(self):
        self.bootstrap()
        next_sweep = 0
        while True:
            if time.time() >= next_sweep:
                self.reconciler.sweep()
                next_sweep = time.time() + 60
            self.once()
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
