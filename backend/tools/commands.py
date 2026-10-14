import base64
import hashlib
import json
import re
import time
import uuid

from execution.storage import MAX_UPLOAD
from execution.telemetry import event
from tools.contracts.errors import AppError
from tools.contracts.models import (
    CANCEL,
    GENERATE,
    READ,
    Artifact,
    AssetPage,
    BrandRevision,
    Caller,
    DataResult,
    ImageCommand,
    JobHandle,
    JobResult,
    RunResult,
)
from tools.conversations import ConversationCommands, conversation_path
from tools.studio_commands import StudioCommands


def identifier(prefix: str) -> str:
    return prefix + "_" + uuid.uuid4().hex


def checked_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value):
        raise AppError("INVALID_INPUT", "Invalid identifier")
    return value


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def project_path(project_id, collection=None, record_id=None):
    path = "projects/" + checked_id(project_id)
    if collection:
        path += "/" + collection
    if record_id:
        path += "/" + checked_id(record_id)
    return path


class Commands(StudioCommands, ConversationCommands):
    def __init__(self, repo, storage, identity, provider, settings, clock=time.time):
        self.repo, self.storage, self.identity = repo, storage, identity
        self.provider, self.settings, self.clock = provider, settings, clock

    def provision(self, caller: Caller):
        self.identity.check_uid(caller.uid, caller.auth_time)

        def apply(tx):
            path = "users/" + checked_id(caller.uid)
            user = tx.get(path)
            if user is None:
                user = {
                    "uid": caller.uid,
                    "access_enabled": True,
                    "access_version": 1,
                    "created_at": self.clock(),
                }
                tx.set(path, user)
            if not user["access_enabled"]:
                raise AppError("ACCESS_DENIED", "Application access is disabled", 403)
            return user

        return self.repo.atomic(apply)

    def authorize(self, caller: Caller, project_id: str, scope=READ, tx=None):
        self.identity.check_uid(caller.uid, caller.auth_time)
        read = tx.get if tx else self.repo.get
        user = read("users/" + checked_id(caller.uid))
        if not user or not user["access_enabled"] or scope not in caller.scopes:
            raise AppError("ACCESS_DENIED", "Application access or scope denied", 403)
        if caller.projects is not None and project_id not in caller.projects:
            raise AppError("ACCESS_DENIED", "Project is outside the granted scope", 403)
        if caller.grant_id:
            grant = read("oauth_grants/" + checked_id(caller.grant_id))
            if not grant or grant.get("revoked") or grant["access_version"] != user["access_version"]:
                raise AppError("ACCESS_DENIED", "MCP grant revoked", 403)
        project = read(project_path(project_id))
        role = (project or {}).get("members", {}).get(caller.uid)
        if not role or (scope != READ and role not in {"owner", "editor"}):
            raise AppError("ACCESS_DENIED", "Project permission denied", 403)
        return project

    def _idempotent(self, tx, path, command, key, value, build, uid):
        mapping_path = path + "/idempotency/" + fingerprint([command, key])
        digest = fingerprint(value)
        previous = tx.get(mapping_path)
        if previous:
            if previous["input_hash"] != digest or previous["uid"] != uid:
                raise AppError("IDEMPOTENCY_CONFLICT", "Idempotency key was used for different input", 409)
            return previous["result"]
        result = build()
        tx.set(
            mapping_path,
            {
                "command": command,
                "input_hash": digest,
                "uid": uid,
                "result": result,
                "created_at": self.clock(),
            },
        )
        return result

    def create_project(self, caller, request):
        self.provision(caller)
        # OAuth/stdio scope cannot be extended by creating projects through a native binding.
        if caller.projects is not None:
            raise AppError("ACCESS_DENIED", "Create projects with Firebase app authentication", 403)

        def apply(tx):
            user = tx.get("users/" + checked_id(caller.uid))
            if not user or not user["access_enabled"]:
                raise AppError("ACCESS_DENIED", "Application access disabled", 403)

            def build():
                project_id = identifier("proj")
                cap = self.settings.project_cap_micros
                if self.settings.provider in {"vertex", "developer"}:
                    cap = min(cap, self.settings.paid_allowance_micros)
                    if tx.get("budgets/account") is None:
                        tx.set(
                            "budgets/account",
                            {
                                "cap_micros": self.settings.paid_allowance_micros,
                                "reserved_micros": 0,
                                "settled_micros": 0,
                                "currency": "USD",
                            },
                        )
                if request.spend_cap_micros is not None:
                    cap = min(cap, request.spend_cap_micros)
                document = {
                    "project_id": project_id,
                    "name": request.name,
                    "owner_uid": caller.uid,
                    "members": {caller.uid: "owner"},
                    "brand_version": 0,
                    "created_at": self.clock(),
                }
                tx.set(project_path(project_id), document)
                tx.set(
                    "budgets/" + project_id,
                    {"cap_micros": cap, "reserved_micros": 0, "settled_micros": 0, "currency": "USD"},
                )
                return document

            return self._idempotent(
                tx,
                "users/" + checked_id(caller.uid),
                "project.create",
                request.idempotency_key,
                request.model_dump(),
                build,
                caller.uid,
            )

        return DataResult(data=self.repo.atomic(apply))

    def list_projects(self, caller):
        self.provision(caller)
        return DataResult(
            data={
                "projects": [
                    {k: p[k] for k in ("project_id", "name", "brand_version")}
                    for p in self.repo.list("projects")
                    if caller.uid in p["members"]
                    and (caller.projects is None or p["project_id"] in caller.projects)
                ]
            }
        )

    def update_brand(self, caller, project_id, request):
        def apply(tx):
            project = self.authorize(caller, project_id, GENERATE, tx)

            def build():
                if request.expected_version != project["brand_version"]:
                    raise AppError("REVISION_CONFLICT", "Brand head changed", 409)
                # Fonts become ready font artifacts in a later slice; reject dangling references now.
                for font_id in request.brand.fonts.values():
                    if self._artifact(project_id, font_id, tx)["type"] != "font":
                        raise AppError("INVALID_INPUT", "Brand fonts require validated font artifacts")
                references = request.brand.reference_frames + (
                    [request.brand.logo] if request.brand.logo else []
                )
                for artifact_id in references:
                    self._artifact(project_id, artifact_id, tx)
                for color in request.brand.colors.values():
                    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                        raise AppError("INVALID_INPUT", "Brand colors must be six-digit hexadecimal values")
                version = project["brand_version"] + 1
                brand = BrandRevision(
                    **request.brand.model_dump(),
                    id=f"brand_{version}",
                    version=version,
                    project_id=project_id,
                    created_at=self.clock(),
                ).model_dump()
                tx.set(project_path(project_id, "brands", f"brand_{version}"), brand)
                project["brand_version"] = version
                tx.set(project_path(project_id), project)
                return brand

            return self._idempotent(
                tx,
                project_path(project_id),
                "brand.update",
                request.idempotency_key,
                request.model_dump(),
                build,
                caller.uid,
            )

        return DataResult(data=self.repo.atomic(apply))

    def get_brand_dna(self, caller, project_id, version=None):
        project = self.authorize(caller, project_id)
        version = project["brand_version"] if version is None else version
        if not isinstance(version, int) or version < 0:
            raise AppError("INVALID_INPUT", "Invalid brand version")
        brand = self.repo.get(project_path(project_id, "brands", f"brand_{version}"))
        if not brand:
            raise AppError("NOT_FOUND", "Brand revision not found", 404)
        return DataResult(data=brand)

    def _artifact(self, project_id, artifact_id, tx=None):
        read = tx.get if tx else self.repo.get
        artifact = read(project_path(project_id, "artifacts", artifact_id))
        if not artifact:
            raise AppError("NOT_FOUND", "Artifact not found", 404)
        lifecycle = read(project_path(project_id, "artifact_lifecycle", artifact_id))
        if not lifecycle or lifecycle["status"] != "ready":
            raise AppError("ARTIFACT_UNAVAILABLE", "Artifact is not available", 409)
        return artifact

    def project_run(self, tx, run):
        tx.set(
            project_path(run["project_id"], "run_summaries", run["run_id"]),
            {
                k: run.get(k)
                for k in (
                    "run_id",
                    "project_id",
                    "status",
                    "version",
                    "brand_version",
                    "pending_approval_id",
                    "created_at",
                )
            },
        )

    def provider_for(self, kind):
        if kind == "image":
            return self.provider
        from providers.studio import StudioProvider

        return StudioProvider(self, kind)

    def generate_image(self, caller, request: ImageCommand):
        return self.submit_job(caller, request, "image")

    def submit_job(
        self, caller, request, kind, parent_run=None, storyboard_override=None, reused_children=None
    ):
        def replay(tx):
            self.authorize(caller, request.project_id, GENERATE, tx)
            previous = tx.get(
                project_path(request.project_id)
                + "/idempotency/"
                + fingerprint([kind + ".generate", request.idempotency_key])
            )
            if previous:
                if (
                    previous["input_hash"] != fingerprint(request.model_dump())
                    or previous["uid"] != caller.uid
                ):
                    raise AppError(
                        "IDEMPOTENCY_CONFLICT", "Idempotency key was used for different input", 409
                    )
                return previous["result"]

        existing = self.repo.atomic(replay)
        if existing:
            return JobHandle(**existing)
        provider = self.provider_for(kind)
        snapshot = provider.snapshot(request.input) if kind == "video" else provider.snapshot()
        if storyboard_override is not None:
            snapshot = {**snapshot, "route": "local", "model": "typed-storyboard-v1", "reservation_micros": 0}
        revision_plan, reused = storyboard_override, reused_children or {}
        if kind == "storyboard" and request.input.revision_of_run_id:
            base_run = self.get_run(caller, request.project_id, request.input.revision_of_run_id)
            flow = base_run.workflow
            if (
                not flow
                or base_run.status != "succeeded"
                or flow.get("composition_artifact_id") != request.input.expected_head
            ):
                raise AppError("REVISION_CONFLICT", "Revision requires the completed current workflow", 409)
            revision_plan = self.get_storyboard(
                caller, request.project_id, flow["storyboard_artifact_id"]
            ).data
            affected = set(request.input.scene_overrides)
            known = {scene["id"] for scene in revision_plan["scenes"]}
            if not affected or not affected <= known:
                raise AppError("INVALID_INPUT", "Choose existing scene ids to revise")
            for scene in revision_plan["scenes"]:
                if scene.get("continuity_from_scene_id") in affected:
                    affected.add(scene["id"])
                if scene["id"] in request.input.scene_overrides:
                    scene["visual_prompt"] = request.input.scene_overrides[scene["id"]]
            reused = {
                k: v
                for k, v in flow["children"].items()
                if k.split(":")[0] not in affected and k not in {"composition", "draft", "export"}
            }
            snapshot = {
                **snapshot,
                "route": "local",
                "model": "typed-scene-revision-v1",
                "reservation_micros": 0,
            }

        def apply(tx):
            project = self.authorize(caller, request.project_id, GENERATE, tx)

            def build():
                for artifact_id in request.input.reference_artifact_ids:
                    artifact = self._artifact(request.project_id, artifact_id, tx)
                    if artifact["media"]["size_bytes"] > MAX_UPLOAD:
                        raise AppError("INVALID_INPUT", "Reference image exceeds provider input limit")
                from tools.studio_commands import validate_submission

                validate_submission(
                    self, caller, request.project_id, kind, request.input, tx, request.conversation_id
                )
                parent = tx.get(project_path(request.project_id, "runs", parent_run)) if parent_run else None
                if parent_run and (not parent or parent["status"] in {"cancelled", "failed", "succeeded"}):
                    raise AppError("CANCELLED", "Parent run no longer accepts work", 409)
                if request.conversation_id:
                    self.conversation(caller, request.project_id, request.conversation_id, tx, GENERATE)
                if parent and parent.get("conversation_id") != request.conversation_id:
                    raise AppError("INVALID_INPUT", "Child job scope does not match its workflow")
                budget_path = "budgets/" + request.project_id
                budget = tx.get(budget_path)
                estimate = snapshot["reservation_micros"]
                if snapshot["route"] in {"vertex", "developer", "cloud_run"}:
                    account = tx.get("budgets/account")
                    if not account or account["reserved_micros"] + account["settled_micros"] + estimate > min(
                        account["cap_micros"], self.settings.paid_allowance_micros
                    ):
                        raise AppError("BUDGET_EXHAUSTED", "Shared account allowance exhausted", 409)
                    account["reserved_micros"] += estimate
                    tx.set("budgets/account", account)
                cap = budget["cap_micros"]
                if request.input.spend_cap_micros is not None:
                    cap = min(cap, request.input.spend_cap_micros)
                if (
                    estimate > cap
                    or budget["reserved_micros"] + budget["settled_micros"] + estimate > budget["cap_micros"]
                ):
                    raise AppError("BUDGET_EXHAUSTED", "Available budget is below the reservation", 409)
                if (
                    parent
                    and parent.get("spent_micros", 0) + parent.get("reserved_micros", 0) + estimate
                    > parent["spend_cap_micros"]
                ):
                    raise AppError("BUDGET_EXHAUSTED", "Run allowance exhausted", 409)
                now = self.clock()
                job_id, run_id, step_id = identifier("job"), identifier("run"), identifier("step")
                run_id = parent_run or run_id
                handle = JobHandle(
                    job_id=job_id, run_id=run_id, step_id=step_id, status="queued"
                ).model_dump()
                brand_version = (
                    parent["brand_version"]
                    if parent
                    else f"brand_{project['brand_version']}"
                    if project["brand_version"]
                    else None
                )
                job = {
                    **handle,
                    "project_id": request.project_id,
                    "conversation_id": request.conversation_id,
                    "kind": kind,
                    "input_artifacts": __import__("tools.studio_commands", fromlist=["input_ids"]).input_ids(
                        kind, request.input
                    ),
                    "caller": caller.model_dump(),
                    "input": request.input.model_dump(),
                    "input_hash": fingerprint(request.input.model_dump()),
                    "provider": snapshot,
                    "brand_version": brand_version,
                    "trace_id": identifier("trace"),
                    "created_at": now,
                    "updated_at": now,
                    "generation": 0,
                    "attempt": 0,
                    "lease_owner": None,
                    "lease_expires_at": 0,
                    "error": None,
                    "cancel_requested": False,
                    "candidate_path": None,
                    "costs": {
                        "reserved_micros": estimate,
                        "settled_micros": 0,
                        "uncertain": False,
                        "basis": "reservation",
                        "currency": "USD",
                    },
                }
                if revision_plan:
                    job["storyboard_override"] = {**revision_plan, "brand_version": brand_version}
                tx.set(project_path(request.project_id, "jobs", job_id), job)
                if parent:
                    parent["job_ids"].append(job_id)
                    parent["reserved_micros"] = parent.get("reserved_micros", 0) + estimate
                    parent["version"] += 1
                    tx.set(project_path(request.project_id, "runs", run_id), parent)
                else:
                    run = {
                        "run_id": run_id,
                        "project_id": request.project_id,
                        "conversation_id": request.conversation_id,
                        "status": "queued",
                        "version": 1,
                        "brand_version": brand_version,
                        "step_id": step_id,
                        "job_id": job_id,
                        "job_ids": [job_id],
                        "spend_cap_micros": cap,
                        "reserved_micros": estimate,
                        "spent_micros": 0,
                        "pending_approval_id": None,
                        "created_at": now,
                    }
                    if kind == "storyboard":
                        run["workflow"] = {
                            "stage": "storyboard",
                            "mode": request.input.workflow_mode,
                            "brief": request.input.model_dump(),
                            "storyboard_job": job_id,
                            "children": reused,
                            "caller": caller.model_dump(),
                        }
                    tx.set(project_path(request.project_id, "runs", run_id), run)
                    self.project_run(tx, run)
                    if kind == "storyboard" and request.conversation_id:
                        cpath = conversation_path(request.project_id, request.conversation_id)
                        conversation = tx.get(cpath)
                        previous_run_id = conversation.get("active_run_id")
                        if previous_run_id and previous_run_id != run_id:
                            previous_path = project_path(request.project_id, "runs", previous_run_id)
                            previous_run = tx.get(previous_path)
                            if previous_run and previous_run["status"] not in {
                                "succeeded",
                                "failed",
                                "cancelled",
                            }:
                                pending_id = previous_run.get("pending_approval_id")
                                if pending_id:
                                    approval_path = project_path(request.project_id, "approvals", pending_id)
                                    approval = tx.get(approval_path)
                                    if approval and approval["decision"] == "pending":
                                        tx.set(approval_path, {**approval, "decision": "superseded"})
                                previous_run.update(
                                    status="cancelled",
                                    pending_approval_id=None,
                                    version=previous_run["version"] + 1,
                                )
                                tx.set(previous_path, previous_run)
                                self.project_run(tx, previous_run)
                        conversation["active_run_id"] = run_id
                        tx.set(cpath, conversation)
                tx.set(
                    project_path(request.project_id, "steps", step_id),
                    {
                        "step_id": step_id,
                        "run_id": run_id,
                        "job_id": job_id,
                        "status": "queued",
                        "required_step_ids": [],
                        "input_artifact_ids": request.input.reference_artifact_ids,
                    },
                )
                budget["reserved_micros"] += estimate
                tx.set(budget_path, budget)
                tx.set(
                    budget_path + "/entries/" + job_id,
                    {
                        "job_id": job_id,
                        "status": "reserved",
                        "estimated_micros": estimate,
                        "reserved_micros": estimate,
                        "settled_micros": 0,
                        "rate": snapshot["rate"],
                        "uncertain": False,
                        "usage": {},
                        "created_at": now,
                    },
                )
                tx.set(
                    project_path(request.project_id, "outbox", job_id),
                    {
                        "id": job_id,
                        "job_id": job_id,
                        "project_id": request.project_id,
                        "status": "pending",
                        "next_attempt_at": now,
                        "attempts": 0,
                        "created_at": now,
                    },
                )
                event("job_submitted", job_id=job_id, run_id=run_id, trace_id=job["trace_id"])
                return handle

            return self._idempotent(
                tx,
                project_path(request.project_id),
                kind + ".generate",
                request.idempotency_key,
                request.model_dump(),
                build,
                caller.uid,
            )

        return JobHandle(**self.repo.atomic(apply))

    def get_job(self, caller, project_id, job_id):
        self.authorize(caller, project_id)
        job = self.repo.get(project_path(project_id, "jobs", job_id))
        if not job:
            raise AppError("NOT_FOUND", "Job not found", 404)
        return JobResult(**{k: job[k] for k in JobResult.model_fields if k in job})

    def get_run(self, caller, project_id, run_id):
        self.authorize(caller, project_id)
        run = self.repo.get(project_path(project_id, "runs", run_id))
        if not run:
            raise AppError("NOT_FOUND", "Run not found", 404)
        jobs = [
            self.repo.get(project_path(project_id, "jobs", j)) for j in run.get("job_ids", [run["job_id"]])
        ]
        approval = (
            self.repo.get(project_path(project_id, "approvals", run["pending_approval_id"]))
            if run.get("pending_approval_id")
            else None
        )
        return self._run_result(run, jobs, approval)

    @staticmethod
    def _run_result(run, jobs, approval):
        return RunResult(
            **{
                k: run[k]
                for k in RunResult.model_fields
                if k in run and k not in {"approval", "active_steps", "workflow"}
            },
            workflow={k: v for k, v in run.get("workflow", {}).items() if k != "caller"} or None,
            approval=approval,
            active_steps=[
                {
                    "step_id": j["step_id"],
                    "job_id": j["job_id"],
                    "status": j["status"],
                    "message": j.get("kind", "image"),
                }
                for j in jobs
                if j
            ][-60:],
        )

    def cancel_job(self, caller, project_id, job_id, idempotency_key):
        def apply(tx):
            self.authorize(caller, project_id, CANCEL, tx)

            def build():
                path = project_path(project_id, "jobs", job_id)
                job = tx.get(path)
                if not job:
                    raise AppError("NOT_FOUND", "Job not found", 404)
                if job["status"] not in {"succeeded", "failed", "cancelled"}:
                    job["cancel_requested"] = True
                    if job["status"] in {"queued", "claimed"}:
                        self.settle(tx, job, 0, "not_submitted", {})
                        job["generation"] += 1
                        job["lease_owner"] = None
                        self.transition(tx, job, "cancelled")
                    elif job["status"] != "submission_unknown":
                        self.transition(tx, job, "cancel_requested")
                    else:
                        self.transition(tx, job, "submission_unknown")
                    run_path = project_path(project_id, "runs", job["run_id"])
                    run = tx.get(run_path)
                    run["status"] = "cancelled"
                    tx.set(run_path, run)
                return {k: job[k] for k in JobHandle.model_fields if k in job}

            return self._idempotent(
                tx,
                project_path(project_id),
                "job.cancel",
                idempotency_key,
                {"job_id": job_id},
                build,
                caller.uid,
            )

        return JobHandle(**self.repo.atomic(apply))

    def cancel_run(self, caller, project_id, run_id, idempotency_key):
        self.authorize(caller, project_id, CANCEL)
        run = self.repo.get(project_path(project_id, "runs", run_id))
        if not run:
            raise AppError("NOT_FOUND", "Run not found", 404)

        def mark(tx):
            current = tx.get(project_path(project_id, "runs", run_id))
            current["status"] = "cancelled"
            current["version"] += 1
            tx.set(project_path(project_id, "runs", run_id), current)

        self.repo.atomic(mark)
        result = None
        for job_id in run.get("job_ids", [run["job_id"]]):
            result = self.cancel_job(caller, project_id, job_id, "run:" + idempotency_key + ":" + job_id)
        return result

    def transition(self, tx, job, status):
        job["status"], job["updated_at"] = status, self.clock()
        tx.set(project_path(job["project_id"], "jobs", job["job_id"]), job)
        run_path = project_path(job["project_id"], "runs", job["run_id"])
        run = tx.get(run_path)
        run_status = {
            "queued": "queued",
            "succeeded": "succeeded",
            "failed": "failed",
            "cancelled": "cancelled",
            "submission_unknown": "needs_reconciliation",
        }.get(status, "running")
        if not run.get("workflow"):
            run["status"] = "cancelled" if job["cancel_requested"] else run_status
        elif status == "submission_unknown":
            run["status"] = "needs_reconciliation"
        run["version"] += 1
        tx.set(run_path, run)
        self.project_run(tx, run)
        step_path = project_path(job["project_id"], "steps", job["step_id"])
        step = tx.get(step_path)
        step["status"] = status
        tx.set(step_path, step)
        tx.set(
            project_path(job["project_id"], "events", f"{run['run_id']}_{run['version']:012d}"),
            {
                "run_id": run["run_id"],
                "job_id": job["job_id"],
                "sequence": run["version"],
                "status": status,
                "created_at": self.clock(),
                "trace_id": job["trace_id"],
            },
        )
        event("job_transition", job_id=job["job_id"], status=status, trace_id=job["trace_id"])

    def settle(self, tx, job, amount, basis, usage):
        budget_path = "budgets/" + job["project_id"]
        entry_path = budget_path + "/entries/" + job["job_id"]
        entry = tx.get(entry_path)
        if entry["status"] == "settled":
            return
        run_path = project_path(job["project_id"], "runs", job["run_id"])
        run = tx.get(run_path)
        if run:
            run["reserved_micros"] = max(0, run.get("reserved_micros", 0) - entry["reserved_micros"])
            run["spent_micros"] = run.get("spent_micros", 0) + amount
            tx.set(run_path, run)
        budget = tx.get(budget_path)
        budget["reserved_micros"] -= entry["reserved_micros"]
        budget["settled_micros"] += amount
        tx.set(budget_path, budget)
        if job["provider"]["route"] in {"vertex", "developer", "cloud_run"}:
            account = tx.get("budgets/account")
            account["reserved_micros"] -= entry["reserved_micros"]
            account["settled_micros"] += amount
            tx.set("budgets/account", account)
        discrepancy = amount - entry["estimated_micros"]
        entry.update(
            status="settled",
            reserved_micros=0,
            settled_micros=amount,
            uncertain=False,
            basis=basis,
            usage=usage,
            discrepancy_micros=discrepancy,
        )
        tx.set(entry_path, entry)
        job["costs"].update(
            reserved_micros=0,
            settled_micros=amount,
            uncertain=False,
            basis=basis,
            discrepancy_micros=discrepancy,
        )
        event("budget_settled", job_id=job["job_id"], amount_micros=amount, discrepancy_micros=discrepancy)

    def get_asset(self, caller, project_id, artifact_id):
        self.authorize(caller, project_id)
        artifact = self._artifact(project_id, artifact_id)
        path = self.repo.get(project_path(project_id, "artifact_lifecycle", artifact_id))["object_path"]
        public = {k: v for k, v in artifact.items() if k != "storage_uri"}
        if self.settings.mode == "production" and not self.settings.local_live:
            public.update(download_url=self.storage.signed_url(path), expires_in_seconds=300)
        else:
            public.update(
                download_url=f"{self.settings.public_url}/v1/projects/{project_id}/assets/{artifact_id}/content",
                requires_authorization=True,
            )
        return DataResult(data=public)

    def asset_content(self, caller, project_id, artifact_id):
        self.authorize(caller, project_id)
        artifact = self._artifact(project_id, artifact_id)
        path = self.repo.get(project_path(project_id, "artifact_lifecycle", artifact_id))["object_path"]
        stored = self.storage.get(path)
        if not stored:
            raise AppError("ARTIFACT_UNAVAILABLE", "Stored artifact unavailable", 409)
        data, _ = stored
        if hashlib.sha256(data).hexdigest() != artifact["content_sha256"]:
            raise AppError("ARTIFACT_UNAVAILABLE", "Artifact content verification failed", 409)
        return data, artifact["media"]["mime_type"]

    def list_assets(self, caller, project_id, limit=20, cursor=None, type=None, status=None):
        self.authorize(caller, project_id)
        if (
            not 1 <= limit <= 100
            or type not in {None, "image", "video", "audio", "composition", "storyboard", "render", "font"}
            or status not in {None, "ready"}
        ):
            raise AppError("INVALID_INPUT", "Unsupported asset query")
        after = ""
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor))
                if (
                    decoded["project_id"] != project_id
                    or decoded["type"] != type
                    or decoded["status"] != status
                ):
                    raise ValueError("Cursor query mismatch")
                after = checked_id(decoded["after"])
            except Exception as exc:
                raise AppError("INVALID_INPUT", "Invalid asset cursor") from exc
        artifacts = self.repo.page(project_path(project_id, "artifacts"), limit + 1, after)
        ready = []
        for artifact in artifacts[:limit]:
            lifecycle = self.repo.get(project_path(project_id, "artifact_lifecycle", artifact["id"]))
            if (
                artifact["id"] > after
                and lifecycle
                and lifecycle["status"] == "ready"
                and artifact["type"] != "director_turn"
                and (type is None or artifact["type"] == type)
            ):
                ready.append({k: v for k, v in artifact.items() if k != "storage_uri"})
        page = ready[:limit]
        next_cursor = None
        if len(artifacts) > limit:
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "project_id": project_id,
                        "after": artifacts[limit - 1]["id"],
                        "type": type,
                        "status": status,
                    }
                ).encode()
            ).decode()
        return AssetPage(assets=page, next_cursor=next_cursor)

    def get_project_context(self, caller, project_id):
        project = self.authorize(caller, project_id)
        return DataResult(data={k: project[k] for k in ("project_id", "name", "brand_version", "created_at")})

    def get_capabilities(self, caller, project_id):
        self.authorize(caller, project_id)
        snapshot = self.provider.snapshot()
        return DataResult(
            data={
                **{k: v for k, v in snapshot.items() if k not in {"rate", "reservation_micros"}},
                "configured_image_model": {
                    "model": self.settings.image_model,
                    "deprecated": self.settings.image_model == "gemini-2.5-flash-image",
                },
                "inputs": ["text", "image"],
                "aspect_ratios": ["9:16", "16:9"],
                "max_references": 3,
                "reference_mime_types": ["image/png", "image/jpeg"],
                "max_reference_bytes": MAX_UPLOAD,
                "execution_style": "synchronous_provider_durable_job",
                "output_images": 1,
                "operations": [
                    "generate_image",
                    "generate_video",
                    "generate_music",
                    "prepare_media",
                    "extract_frame",
                    "create_video",
                    "create_hyperframe",
                    "update_hyperframe",
                    "get_hyperframe",
                    "render_hyperframe",
                ],
                "workflow": {
                    "storyboard_approval": "human_app",
                    "preview_approval": "human_app",
                    "max_scenes": 5,
                    "fps": 24,
                    "default_duration_seconds": 15,
                },
                "renderer": {"runtime": "hyperframes@0.8.116", "runner": self.settings.render_runner},
            }
        )

    def initiate_upload(self, caller, project_id, request):
        def apply(tx):
            self.authorize(caller, project_id, GENERATE, tx)

            def build():
                limit = (
                    MAX_UPLOAD
                    if request.mime_type.startswith("image/")
                    else 2_000_000
                    if request.mime_type.startswith("font/")
                    else self.settings.max_media_bytes
                )
                if request.size_bytes > limit:
                    raise AppError("INVALID_MEDIA", "Upload exceeds this media type limit")
                upload_id = identifier("upload")
                record = {
                    "upload_id": upload_id,
                    "project_id": project_id,
                    "uid": caller.uid,
                    **request.model_dump(exclude={"idempotency_key"}),
                    "status": "pending",
                    "object_path": f"projects/{project_id}/imports/{upload_id}",
                    "created_at": self.clock(),
                    "expires_at": self.clock() + 300,
                }
                tx.set(project_path(project_id, "uploads", upload_id), record)
                return record

            return self._idempotent(
                tx,
                project_path(project_id),
                "asset.upload",
                request.idempotency_key,
                request.model_dump(),
                build,
                caller.uid,
            )

        record = self.repo.atomic(apply)
        url = f"{self.settings.public_url}/v1/projects/{project_id}/uploads/{record['upload_id']}/content"
        headers = {"Content-Type": record["mime_type"]}
        if self.settings.mode == "production" and not self.settings.local_live:
            url = self.storage.signed_url(record["object_path"], "PUT", record["mime_type"])
            headers["x-goog-if-generation-match"] = "0"
        return DataResult(
            data={
                "upload_id": record["upload_id"],
                "upload_url": url,
                "headers": headers,
                "expires_at": record["expires_at"],
                "requires_authorization": self.settings.mode == "emulator" or self.settings.local_live,
            }
        )

    def upload_content(self, caller, project_id, upload_id, data, mime_type):
        self.authorize(caller, project_id, GENERATE)
        record = self.repo.get(project_path(project_id, "uploads", upload_id))
        if not record or record["uid"] != caller.uid or record["expires_at"] < self.clock():
            raise AppError("ACCESS_DENIED", "Upload is unavailable or expired", 403)
        if len(data) != record["size_bytes"] or mime_type != record["mime_type"]:
            raise AppError("INVALID_MEDIA", "Upload size or MIME type does not match")
        from tools.media.pipeline import inspect_upload

        metadata = inspect_upload(data, mime_type)
        self.storage.put(record["object_path"], data, metadata)
        return DataResult(data={"upload_id": upload_id, "uploaded": True})

    def complete_upload(self, caller, project_id, request):
        self.authorize(caller, project_id, GENERATE)
        path = project_path(project_id, "uploads", request.upload_id)
        record = self.repo.get(path)
        if not record or record["uid"] != caller.uid:
            raise AppError("NOT_FOUND", "Upload not found", 404)
        stored = self.storage.get(record["object_path"])
        if not stored:
            raise AppError("UPLOAD_INCOMPLETE", "Upload has not completed", 409)
        from tools.media.pipeline import inspect_upload

        media = inspect_upload(stored[0], record["mime_type"])
        if media["size_bytes"] != record["size_bytes"]:
            raise AppError("INVALID_MEDIA", "Uploaded size does not match")
        artifact_id = "art_" + request.upload_id.removeprefix("upload_")

        def apply(tx):
            self.authorize(caller, project_id, GENERATE, tx)

            def build():
                current = tx.get(path)
                if current["status"] == "ready":
                    return tx.get(project_path(project_id, "artifacts", artifact_id))
                if current["expires_at"] < self.clock():
                    raise AppError("UPLOAD_EXPIRED", "Upload completion expired", 409)
                artifact = Artifact(
                    id=artifact_id,
                    project_id=project_id,
                    title=record["title"],
                    type="font"
                    if record["mime_type"].startswith("font/")
                    else "audio"
                    if record["mime_type"].startswith("audio/")
                    else "video"
                    if record["mime_type"].startswith("video/")
                    else "image",
                    storage_uri=self.storage.uri(record["object_path"]),
                    content_sha256=media["content_sha256"],
                    media=media,
                    created_at=self.clock(),
                ).model_dump()
                tx.set(project_path(project_id, "artifacts", artifact_id), artifact)
                tx.set(
                    project_path(project_id, "artifact_lifecycle", artifact_id),
                    {"status": "ready", "object_path": record["object_path"], "current": True},
                )
                current["status"] = "ready"
                tx.set(path, current)
                return artifact

            return self._idempotent(
                tx,
                project_path(project_id),
                "asset.complete",
                request.idempotency_key,
                request.model_dump(),
                build,
                caller.uid,
            )

        result = self.repo.atomic(apply)
        return DataResult(data={k: v for k, v in result.items() if k != "storage_uri"})
