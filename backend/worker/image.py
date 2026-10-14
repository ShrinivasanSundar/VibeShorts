import threading

from execution.telemetry import event
from providers.image import ProviderFailure
from providers.studio import inspect_output
from tools.commands import identifier, project_path
from tools.contracts.errors import AppError
from tools.contracts.models import Artifact, Caller, ImageInput
from tools.contracts.studio import INPUTS
from tools.conversations import append_message, head_path

TERMINAL = {"succeeded", "failed", "cancelled", "submission_unknown"}


class ImageWorker:
    def __init__(self, commands):
        self.commands = commands
        self.repo, self.storage = commands.repo, commands.storage

    def claim(self, project_id, job_id):
        owner = identifier("worker")

        def apply(tx):
            job = tx.get(project_path(project_id, "jobs", job_id))
            if not job or job["status"] in TERMINAL:
                return None
            now = self.commands.clock()
            if job["lease_owner"] and job["lease_expires_at"] > now:
                return None
            if job["status"] not in {
                "queued",
                "claimed",
                "materializing",
                "waiting_for_provider",
                "cancel_requested",
            }:
                return None  # Reconciler owns uncertain provider-submission recovery.
            if job["status"] in {"waiting_for_provider", "cancel_requested"} and not job.get(
                "provider_operation"
            ):
                return None
            if job.get("next_poll_at", 0) > now:
                return None
            job["generation"] += 1
            job["lease_owner"], job["lease_expires_at"] = owner, now + self.commands.settings.lease_seconds
            self.commands.transition(
                tx, job, "materializing" if job["status"] == "materializing" else "claimed"
            )
            return job

        return self.repo.atomic(apply)

    def _current(self, tx, claimed):
        current = tx.get(project_path(claimed["project_id"], "jobs", claimed["job_id"]))
        if (
            not current
            or current["lease_owner"] != claimed["lease_owner"]
            or current["generation"] != claimed["generation"]
            or current["lease_expires_at"] <= self.commands.clock()
        ):
            raise AppError("STALE_LEASE", "Worker no longer owns this job", 409)
        return current

    def heartbeat(self, claimed):
        def apply(tx):
            current = self._current(tx, claimed)
            current["lease_expires_at"] = self.commands.clock() + self.commands.settings.lease_seconds
            tx.set(project_path(current["project_id"], "jobs", current["job_id"]), current)

        self.repo.atomic(apply)

    def _heartbeat_loop(self, claimed, stopped):
        while not stopped.wait(self.commands.settings.lease_seconds / 3):
            try:
                self.heartbeat(claimed)
            except Exception:
                return

    def execute(self, project_id, job_id):
        job = self.claim(project_id, job_id)
        if not job:
            return False
        stopped = threading.Event()
        heartbeat = threading.Thread(target=self._heartbeat_loop, args=(job, stopped), daemon=True)
        heartbeat.start()
        try:
            caller = Caller(**job["caller"])
            if job["status"] == "materializing":
                self.materialize(job)
                return True
            self.commands.authorize(caller, project_id, "vibeshorts:generate")
            kind = job.get("kind", "image")
            provider = self.commands.provider_for(kind)
            if (
                not job.get("storyboard_override")
                and provider.snapshot()["route"] != job["provider"]["route"]
            ):
                raise AppError("PROVIDER_UNAVAILABLE", "Accepted provider route is not configured", 503)
            request = (ImageInput if kind == "image" else INPUTS[kind])(**job["input"])
            references = [
                self.commands.asset_content(caller, project_id, a)[0]
                for a in job.get("input_artifacts", request.reference_artifact_ids)
            ]

            def submitting(tx):
                current = self._current(tx, job)
                self.commands.authorize(caller, project_id, "vibeshorts:generate", tx)
                if current["cancel_requested"]:
                    raise AppError("CANCELLED", "Job cancelled", 409)
                from tools.studio_commands import validate_submission

                validate_submission(
                    self.commands, caller, project_id, kind, request, tx, job.get("conversation_id")
                )
                current["attempt"] += 1
                current["candidate_path"] = (
                    f"projects/{project_id}/jobs/{job_id}/attempt_{current['attempt']}/image"
                )
                self.commands.transition(tx, current, "submitting")
                return current

            if kind in {"video", "render"} and job.get("provider_operation"):
                output, operation = (
                    provider.poll_video(job["provider_operation"], job["provider"])
                    if kind == "video"
                    else provider.poll_render(job["provider_operation"])
                )
                if output is None:
                    self.wait_for_provider(job, operation)
                    return True
            else:
                job = self.repo.atomic(submitting)
                if kind == "render" and self.commands.settings.render_runner == "cloud_run":
                    operation = provider.submit_render(request, job)
                    self.wait_for_provider(job, operation)
                    return True
                if kind == "video" and job["provider"]["route"] != "fixture":
                    operation = provider.submit_video(request, references[0], job["provider"])
                    self.wait_for_provider(job, operation)
                    return True
                output = (
                    provider.generate(request, references, job["provider"])
                    if kind == "image"
                    else provider.generate(request, references, job["provider"], job)
                )
            event(
                "provider_invocation", job_id=job_id, route=job["provider"]["route"], trace_id=job["trace_id"]
            )
            metadata = inspect_output(kind, output.data, output.mime_type)
            expected = 9 / 16 if getattr(request, "aspect_ratio", "9:16") == "9:16" else 16 / 9
            if (
                kind in {"image", "video"}
                and abs(metadata["width"] / metadata["height"] - expected) / expected > 0.05
            ):
                raise ProviderFailure(
                    "INVALID_PROVIDER_OUTPUT", "Provider image has the wrong aspect ratio", uncertain=True
                )
            amount, basis = provider.cost(output.usage, job["provider"])
            # Metadata and bytes become durable together. Reconciliation can recover this
            # object even if the process dies before the following database transition.
            self.storage.put(
                job["candidate_path"],
                output.data,
                {
                    **metadata,
                    "usage": output.usage,
                    "amount_micros": amount,
                    "cost_basis": basis,
                    "input_hash": job["input_hash"],
                    "attempt": job["attempt"],
                },
            )

            def ready(tx):
                current = self._current(tx, job)
                self.commands.transition(tx, current, "materializing")
                return current

            job = self.repo.atomic(ready)
            self.materialize(job)
            return True
        except ProviderFailure as exc:
            self.fail(job, exc, uncertain=exc.uncertain)
        except Exception as exc:
            if job.get("provider_operation") and not isinstance(exc, AppError):
                self.wait_for_provider(job, job["provider_operation"])
                event("provider_poll_failure", job_id=job_id, exception_type=type(exc).__name__)
                return True
            if isinstance(exc, AppError) and exc.payload.code == "STALE_LEASE":
                return True
            current = self.repo.get(project_path(project_id, "jobs", job_id))
            uncertain = current and current["status"] in {"submitting", "cancel_requested", "materializing"}
            self.fail(
                job,
                exc
                if isinstance(exc, AppError)
                else AppError("EXECUTION_FAILED", "Media execution failed", 503),
                uncertain=bool(uncertain) and job["provider"]["route"] not in {"local", "fixture"},
            )
            event("worker_failure", job_id=job_id, exception_type=type(exc).__name__)
            return True
        finally:
            stopped.set()
            heartbeat.join(timeout=1)

    def wait_for_provider(self, claimed, operation):
        def apply(tx):
            current = self._current(tx, claimed)
            current["provider_operation"] = operation
            current["lease_owner"], current["lease_expires_at"] = None, 0
            current["next_poll_at"] = self.commands.clock() + 10
            self.commands.transition(tx, current, "waiting_for_provider")
            path = project_path(current["project_id"], "outbox", current["job_id"])
            tx.set(
                path,
                {
                    "id": current["job_id"],
                    "job_id": current["job_id"],
                    "project_id": current["project_id"],
                    "status": "pending",
                    "next_attempt_at": current["next_poll_at"],
                    "attempts": 0,
                    "created_at": self.commands.clock(),
                },
            )

        self.repo.atomic(apply)

    def fail(self, claimed, error, uncertain=False):
        def apply(tx):
            current = self._current(tx, claimed)
            current["lease_owner"], current["lease_expires_at"] = None, 0
            if uncertain:
                current["costs"]["uncertain"] = True
                path = "budgets/" + current["project_id"] + "/entries/" + current["job_id"]
                entry = tx.get(path)
                entry.update(uncertain=True, status="uncertain")
                tx.set(path, entry)
                current["error"] = AppError(
                    "PROVIDER_SUBMISSION_UNCERTAIN",
                    "The provider may have accepted this request",
                    503,
                    action="reconcile",
                    job_id=current["job_id"],
                ).payload.model_dump()
                self.commands.transition(tx, current, "submission_unknown")
                event("uncertain_submission", job_id=current["job_id"])
            else:
                # Provider safety inference may incur usage even when it returns no image.
                charge = (
                    current["provider"]["reservation_micros"]
                    if error.payload.code == "SAFETY_REJECTED"
                    or current.get("provider_operation")
                    or getattr(error, "usage", None)
                    else 0
                )
                self.commands.settle(
                    tx,
                    current,
                    charge,
                    "conservative_estimate" if charge else "not_submitted",
                    getattr(error, "usage", {}),
                )
                current["error"] = error.payload.model_dump()
                cancelled = current["cancel_requested"] or error.payload.code in {
                    "ACCESS_DENIED",
                    "CANCELLED",
                }
                self.commands.transition(tx, current, "cancelled" if cancelled else "failed")
            if current.get("conversation_id") and current["kind"] != "director_turn":
                run = tx.get(project_path(current["project_id"], "runs", current["run_id"]))
                append_message(
                    self.commands,
                    tx,
                    current["project_id"],
                    current["conversation_id"],
                    "job-error:" + current["job_id"] + ":" + current["status"],
                    "assistant",
                    current["error"]["message"],
                    [
                        {
                            "kind": "error",
                            "job_id": current["job_id"],
                            "retryable": not bool(run and run.get("workflow")),
                        }
                    ],
                )

        try:
            self.repo.atomic(apply)
        except AppError as exc:
            if exc.payload.code != "STALE_LEASE":
                raise

    def materialize(self, claimed):
        stored = self.storage.get(claimed["candidate_path"])
        if not stored:
            raise AppError("ARTIFACT_UNAVAILABLE", "Candidate object is unavailable", 409)
        data, metadata = stored
        kind = claimed.get("kind", "image")
        media = inspect_output(kind, data, metadata.get("mime_type"))
        if (
            metadata.get("input_hash") != claimed["input_hash"]
            or metadata.get("attempt") != claimed["attempt"]
            or metadata.get("content_sha256") != media["content_sha256"]
        ):
            raise AppError("INVALID_MEDIA", "Candidate verification failed")
        artifact_id = "art_" + claimed["job_id"].removeprefix("job_")

        def apply(tx):
            current = self._current(tx, claimed)
            try:
                self.commands.authorize(
                    Caller(**current["caller"]), current["project_id"], "vibeshorts:generate", tx
                )
            except AppError:
                current["cancel_requested"] = True
            self.commands.settle(
                tx, current, metadata["amount_micros"], metadata["cost_basis"], metadata["usage"]
            )
            if kind == "render" and current["input"]["quality"] == "final":
                project = tx.get(head_path(current["project_id"], current.get("conversation_id")))
                if project.get("composition_head") != current["input"]["composition_artifact_id"]:
                    current["cancel_requested"] = True
            if not current["cancel_requested"]:
                artifact = Artifact(
                    id=artifact_id,
                    project_id=current["project_id"],
                    run_id=current["run_id"],
                    job_id=current["job_id"],
                    input_artifact_ids=(
                        __import__("tools.composition.package", fromlist=["unpack"]).unpack(data)[0][
                            "input_artifact_ids"
                        ]
                        if kind in {"composition", "edit"}
                        else current.get("input_artifacts", current["input"]["reference_artifact_ids"])
                    ),
                    parent_id=current["input"].get("expected_head"),
                    type={
                        "music": "audio",
                        "prepare": "audio" if media["mime_type"].startswith("audio/") else "video",
                        "frame": "image",
                        "edit": "composition",
                    }.get(kind, kind),
                    title={
                        "image": "Generated image",
                        "video": "Video plate",
                        "music": "Instrumental music",
                        "prepare": "Prepared media",
                        "frame": "Continuity frame",
                        "storyboard": "Storyboard",
                        "director_turn": "Director response",
                        "edit": "Edited composition",
                        "composition": current["input"].get("title", "Composition"),
                        "render": "Draft preview"
                        if current["input"].get("quality") == "draft"
                        else "Final export",
                    }[kind],
                    storage_uri=self.storage.uri(current["candidate_path"]),
                    content_sha256=media["content_sha256"],
                    media=media,
                    brand_version=current["brand_version"],
                    provider={k: current["provider"][k] for k in ("route", "model", "location")},
                    created_at=self.commands.clock(),
                ).model_dump()
                if kind in {"composition", "edit"}:
                    project = tx.get(head_path(current["project_id"], current.get("conversation_id")))
                    if project.get("composition_head") != current["input"].get("expected_head"):
                        raise AppError("REVISION_CONFLICT", "Composition head advanced", 409)
                    old_head = project.get("composition_head")
                    if old_head:
                        old_path = project_path(current["project_id"], "artifact_lifecycle", old_head)
                        old = tx.get(old_path)
                        if old:
                            old["current"] = False
                        tx.set(old_path, old)
                    project["composition_head"] = artifact_id
                    tx.set(head_path(current["project_id"], current.get("conversation_id")), project)
                tx.set(project_path(current["project_id"], "artifacts", artifact_id), artifact)
                tx.set(
                    project_path(current["project_id"], "artifact_lifecycle", artifact_id),
                    {"status": "ready", "object_path": current["candidate_path"], "current": True},
                )
                current["artifact_ids"] = [artifact_id]
                cid = current.get("conversation_id")
                parent = tx.get(project_path(current["project_id"], "runs", current["run_id"]))
                if cid and kind in {"composition", "edit"} and not parent.get("workflow"):
                    approval_id = "approval_" + artifact_id + "_preview"
                    approval = {
                        "id": approval_id,
                        "kind": "preview",
                        "run_id": None,
                        "conversation_id": cid,
                        "target_artifact_id": artifact_id,
                        "decision": "pending",
                        "created_at": self.commands.clock(),
                        "review_url": f"{self.commands.settings.web_url}/projects/{current['project_id']}",
                    }
                    tx.set(project_path(current["project_id"], "approvals", approval_id), approval)
                    append_message(
                        self.commands,
                        tx,
                        current["project_id"],
                        cid,
                        "composition:" + artifact_id,
                        "assistant",
                        "Your updated video is ready for review.",
                        [{"kind": "composition", "artifact_id": artifact_id}],
                    )
                if (
                    cid
                    and kind == "render"
                    and current["input"]["quality"] == "final"
                    and not parent.get("workflow")
                ):
                    append_message(
                        self.commands,
                        tx,
                        current["project_id"],
                        cid,
                        "export:" + artifact_id,
                        "assistant",
                        "Your video is ready to download.",
                        [{"kind": "export", "artifact_id": artifact_id}],
                    )
            current["lease_owner"], current["lease_expires_at"], current["error"] = None, 0, None
            self.commands.transition(tx, current, "cancelled" if current["cancel_requested"] else "succeeded")

        self.repo.atomic(apply)
