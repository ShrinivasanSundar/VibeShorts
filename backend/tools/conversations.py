"""Project-owned conversations. Jobs remain authoritative for execution and media."""

import hashlib

from tools.contracts.errors import AppError
from tools.contracts.models import CANCEL, GENERATE, Caller, DataResult
from tools.contracts.studio import (
    ApprovalDecision,
    BriefInput,
    ConversationInput,
    ConversationMessage,
    CreativePreferences,
    DirectorTurn,
    EditInput,
    Storyboard,
    StudioCommand,
)

TERMINAL = {"succeeded", "failed", "cancelled", "submission_unknown"}


def conversation_path(project, conversation):
    from tools.commands import checked_id, project_path

    return project_path(project, "conversations", checked_id(conversation))


def head_path(project, conversation=None):
    from tools.commands import project_path

    return conversation_path(project, conversation) if conversation else project_path(project)


def conversation_request_value(body):
    """Keep legacy idempotency hashes stable when new options are unused."""
    value = body.model_dump()
    for field in ("composition_artifact_id", "creative_preferences"):
        if value.get(field) is None:
            value.pop(field, None)
    if isinstance(body, ConversationMessage):
        if value.get("workflow_mode") is None:
            value.pop("workflow_mode", None)
        if value.get("policy") == "product_launch":
            value.pop("policy", None)
    return value


def append_message(commands, tx, project, conversation, source, role, text, blocks=None, **extra):
    path = conversation_path(project, conversation)
    marker = path + "/message_keys/" + hashlib.sha256(source.encode()).hexdigest()
    existing = tx.get(marker)
    if existing:
        return tx.get(path + "/messages/" + existing["id"])
    doc = tx.get(path)
    if not doc:
        raise AppError("NOT_FOUND", "Conversation not found", 404)
    sequence = doc.get("sequence", 0) + 1
    revision = doc.get("revision", 0) + 1
    message = {
        "id": f"message_{sequence:012d}",
        "sequence": sequence,
        "revision": revision,
        "role": role,
        "text": text,
        "blocks": blocks or [],
        "created_at": commands.clock(),
        **extra,
    }
    doc.update(sequence=sequence, revision=revision, updated_at=commands.clock())
    tx.set(path, doc)
    tx.set(path + "/messages/" + message["id"], message)
    tx.set(marker, {"id": message["id"]})
    return message


def set_message(tx, path, message):
    """Write a message and bump the conversation revision.

    The revision lets clients listen to the conversation document and fetch only messages
    written since the revision they already hold.
    """
    doc = tx.get(path)
    if not doc:
        return
    doc["revision"] = doc.get("revision", 0) + 1
    tx.set(path, doc)
    tx.set(path + "/messages/" + message["id"], {**message, "revision": doc["revision"]})


class ConversationCommands:
    def conversation(self, caller, project, conversation, tx=None, scope=None):
        self.authorize(caller, project, scope or "vibeshorts:read", tx)
        doc = (tx or self.repo).get(conversation_path(project, conversation))
        if not doc or doc.get("deleting"):
            raise AppError("NOT_FOUND", "Conversation not found", 404)
        return doc

    def create_conversation(self, caller, project, body):
        from tools.commands import identifier, project_path

        def apply(tx):
            self.authorize(caller, project, GENERATE, tx)

            def build():
                cid = identifier("chat")
                now = self.clock()
                doc = {
                    "id": cid,
                    "title": body.title,
                    "created_at": now,
                    "updated_at": now,
                    "sequence": 0,
                    "composition_head": None,
                    "storyboard_head": None,
                    "active_run_id": None,
                    "workflow_mode": body.workflow_mode,
                    "owner_uid": caller.uid,
                }
                if body.run_id:
                    run = tx.get(project_path(project, "runs", body.run_id))
                    if not run or not run.get("workflow"):
                        raise AppError("NOT_FOUND", "Video workflow not found", 404)
                    if run.get("conversation_id"):
                        return tx.get(conversation_path(project, run["conversation_id"]))
                    doc.update(
                        active_run_id=body.run_id,
                        workflow_mode=run["workflow"].get("mode", "bulk"),
                        composition_head=run["workflow"].get("composition_artifact_id"),
                        storyboard_head=run["workflow"].get("storyboard_artifact_id"),
                        title=run["workflow"]["brief"]["brief"][:120],
                    )
                    run["conversation_id"] = cid
                    tx.set(project_path(project, "runs", body.run_id), run)
                    pending_id = run.get("pending_approval_id")
                    if pending_id:
                        approval_path = project_path(project, "approvals", pending_id)
                        approval = tx.get(approval_path)
                        if approval and approval["decision"] == "pending":
                            tx.set(approval_path, {**approval, "conversation_id": cid})
                    for jid in run.get("job_ids", []):
                        job = tx.get(project_path(project, "jobs", jid))
                        if job:
                            if not doc["composition_head"] and job["kind"] in {"composition", "edit"}:
                                doc["composition_head"] = (
                                    job["artifact_ids"][0]
                                    if job["status"] == "succeeded"
                                    else job["input"].get("expected_head")
                                )
                            job["conversation_id"] = cid
                            tx.set(project_path(project, "jobs", jid), job)
                if body.composition_artifact_id:
                    artifact = self._artifact(project, body.composition_artifact_id, tx)
                    if artifact["type"] != "composition":
                        raise AppError("INVALID_INPUT", "Choose an editable composition")
                    doc["composition_head"] = body.composition_artifact_id
                    doc["title"] = artifact.get("title", body.title)[:120]
                tx.set(conversation_path(project, cid), doc)
                if body.composition_artifact_id:
                    append_message(
                        self,
                        tx,
                        project,
                        cid,
                        "import-composition",
                        "assistant",
                        "Your existing cut is ready to review or edit. "
                        "Export requires approval of this exact version.",
                        [{"kind": "composition", "artifact_id": body.composition_artifact_id}],
                    )
                if body.run_id:
                    append_message(
                        self,
                        tx,
                        project,
                        cid,
                        "import",
                        "assistant",
                        "This video was started in Studio. Its existing workflow and review checkpoints"
                        " are preserved.",
                    )
                return tx.get(conversation_path(project, cid))

            return self._idempotent(
                tx,
                project_path(project),
                "conversation.create",
                body.idempotency_key,
                conversation_request_value(body),
                build,
                caller.uid,
            )

        return DataResult(data=self.repo.atomic(apply))

    def list_conversations(self, caller, project, limit=30, cursor=None):
        from tools.commands import project_path

        self.authorize(caller, project)
        docs = self.repo.latest(project_path(project, "conversations"), "updated_at", limit + 1, cursor or "")
        more, docs = len(docs) > limit, docs[:limit]
        return DataResult(
            data={
                "conversations": [d for d in docs if not d.get("deleting")],
                "next_cursor": docs[-1]["id"] if more else None,
            }
        )

    def conversation_state(
        self, caller, project, conversation, cursor=None, limit=50, tail=False, since=None
    ):
        from tools.commands import project_path

        # Read the conversation before its messages so the returned revision never runs ahead of them.
        doc = self.conversation(caller, project, conversation)
        path = conversation_path(project, conversation)
        incremental = False
        if since is not None and not cursor:
            # Only messages written after the caller's revision; fall back to a full tail if too many.
            changed = self.repo.above(path + "/messages", "revision", since, limit + 1)
            if len(changed) <= limit:
                incremental, messages = True, []
                page = sorted(changed, key=lambda m: m["sequence"])
        if not incremental:
            messages = (self.repo.tail if tail else self.repo.page)(
                path + "/messages", limit + 1, cursor or ""
            )
            page = list(reversed(messages[:limit])) if tail else messages[:limit]
        run = self._load_run(project, doc["active_run_id"]).model_dump() if doc["active_run_id"] else None
        return DataResult(
            data={
                "revision": doc.get("revision", 0),
                "incremental": incremental,
                "conversation": doc,
                "production": self.production_summary(caller, project, doc, run),
                "messages": [{k: v for k, v in m.items() if k not in {"caller", "request"}} for m in page],
                "run": run,
                "operations": [
                    {
                        "job_id": j["job_id"],
                        "kind": j["kind"],
                        "status": j["status"],
                        "quality": j["input"].get("quality"),
                        "error": j.get("error"),
                        "retried_by": j.get("retried_by"),
                    }
                    for j in self.repo.recent_where(
                        project_path(project, "jobs"), "conversation_id", conversation, 15
                    )
                ],
                "next_cursor": messages[limit - 1]["id"] if len(messages) > limit else None,
            }
        )

    def production_summary(self, caller, project, doc, run):
        """Current artifacts from all workflow dependencies, including reused jobs."""
        from tools.commands import project_path

        flow = (run or {}).get("workflow") or {}
        story = self._storyboard(caller, project, doc["storyboard_head"]) if doc["storyboard_head"] else None
        children = flow.get("children", {})
        # Every child job is read in one batched round trip rather than one read per step.
        loaded = dict(
            zip(
                children.values(),
                self.repo.get_many([project_path(project, "jobs", jid) for jid in children.values()]),
                strict=True,
            )
        )

        def step(key):
            jid = children.get(key)
            job = loaded.get(jid) if jid else None
            return {
                "job_id": jid,
                "status": job["status"] if job else "pending",
                "artifact_id": job["artifact_ids"][0]
                if job and job["status"] == "succeeded" and job["artifact_ids"]
                else None,
                "error": job.get("error") if job else None,
                "created_at": job.get("created_at") if job else None,
                "updated_at": job.get("updated_at") if job else None,
            }

        return {
            "storyboard": story,
            "mode": flow.get("mode", doc["workflow_mode"]),
            "stage": flow.get("stage", "preview" if doc["composition_head"] else "idea"),
            "scenes": [
                {
                    **scene,
                    "frame": step(
                        scene["id"] + (":anchor" if scene.get("continuity_from_scene_id") else ":keyframe")
                    ),
                    "video": step(scene["id"] + ":prepared"),
                    "generation": step(scene["id"] + ":plate"),
                }
                for scene in (story or {}).get("scenes", [])
            ],
            "music": step("music:prepared"),
            "music_generation": step("music"),
            "composition": step("composition"),
            "draft": step("draft"),
            "export": step("export"),
            "affected_scene_ids": flow.get("affected_scene_ids", []),
        }

    def send_message(self, caller, project, conversation, body):
        from tools.commands import project_path

        def apply(tx):
            doc = self.conversation(caller, project, conversation, tx, GENERATE)
            for aid in body.reference_artifact_ids:
                if self._artifact(project, aid, tx)["type"] != "image":
                    raise AppError("INVALID_INPUT", "Storyboard references must be images")

            def build():
                message = append_message(
                    self,
                    tx,
                    project,
                    conversation,
                    "user:" + body.idempotency_key,
                    "user",
                    body.text,
                    [{"kind": "attachment", "artifact_id": aid} for aid in body.reference_artifact_ids],
                    status="queued",
                    request=body.model_dump(),
                    uid=caller.uid,
                    caller=caller.model_dump(),
                )
                current = tx.get(conversation_path(project, conversation))
                current["latest_request_id"] = message["id"]
                if doc["title"] == "New video":
                    current["title"] = body.text[:120]
                tx.set(conversation_path(project, conversation), current)
                self.enqueue_advance(tx, project, "conversation", conversation)
                return {"message_id": message["id"], "status": "queued"}

            return self._idempotent(
                tx,
                project_path(project),
                "conversation.message:" + conversation,
                body.idempotency_key,
                conversation_request_value(body) | {"conversation_id": conversation},
                build,
                caller.uid,
            )

        return DataResult(data=self.repo.atomic(apply))

    def conversation_action(self, caller, project, conversation, body):
        from tools.commands import project_path

        doc = self.conversation(
            caller, project, conversation, scope=CANCEL if body.action == "cancel" else GENERATE
        )
        if body.action == "remove_scene":
            if not body.scene_id:
                raise AppError("INVALID_INPUT", "Choose a scene to delete")
            return self.remove_scene(caller, project, conversation, body.scene_id, body.idempotency_key)
        if body.action == "revise":
            if not body.instruction:
                raise AppError("INVALID_INPUT", "Describe the revision")
            return self.send_message(
                caller,
                project,
                conversation,
                ConversationMessage(idempotency_key=body.idempotency_key, text=body.instruction),
            )
        if body.action in {"approve", "continue"}:
            if not body.approval_id or not body.target_artifact_id:
                raise AppError("INVALID_INPUT", "An exact review target is required")
            approval = self.repo.get(project_path(project, "approvals", body.approval_id))
            if not approval or approval.get("conversation_id") != conversation:
                raise AppError("REVISION_CONFLICT", "This review belongs to another video", 409)
            return self.decide_approval(
                caller,
                project,
                body.approval_id,
                ApprovalDecision(
                    idempotency_key=body.idempotency_key,
                    target_artifact_id=body.target_artifact_id,
                    approved=True,
                ),
            )
        if body.action == "cancel":
            # Stop queued conversation requests as well as current media.
            for message in self.repo.list(conversation_path(project, conversation) + "/messages"):
                if message.get("status") in {"queued", "running"}:
                    if message.get("job_id"):
                        self.cancel_job(
                            caller, project, message["job_id"], body.idempotency_key + message["id"]
                        )
                    self.repo.atomic(
                        lambda tx, m=message: set_message(
                            tx, conversation_path(project, conversation), {**m, "status": "cancelled"}
                        )
                    )
            # Standalone edits and renders also belong to this conversation.
            for job in self.repo.list_where(project_path(project, "jobs"), "conversation_id", [conversation]):
                if job["status"] not in TERMINAL:
                    self.cancel_job(caller, project, job["job_id"], body.idempotency_key + job["job_id"])
            if doc["active_run_id"]:
                run = self.repo.get(project_path(project, "runs", doc["active_run_id"]))
                if run and run["status"] not in TERMINAL:
                    self.cancel_run(caller, project, doc["active_run_id"], body.idempotency_key)
            return DataResult(data={"status": "cancelled"})
        if body.action == "retry" and body.job_id:
            from tools.contracts.studio import INPUTS

            job = self.repo.get(project_path(project, "jobs", body.job_id))
            if not job or job.get("conversation_id") != conversation:
                raise AppError("REVISION_CONFLICT", "This operation belongs to another video", 409)
            run = self.repo.get(project_path(project, "runs", job["run_id"]))
            if (
                job["status"] != "failed"
                or (run and run.get("workflow"))
                or job["kind"] not in {"director_turn", "edit", "composition", "render"}
            ):
                raise AppError(
                    "REVISION_CONFLICT",
                    "Only a confirmed failed standalone request can be retried",
                    409,
                )
            retry_message = None
            if job["kind"] == "director_turn" and not job.get("retried_by"):
                users = sorted(
                    (
                        m
                        for m in self.repo.list(conversation_path(project, conversation) + "/messages")
                        if m["role"] == "user"
                    ),
                    key=lambda m: m["sequence"],
                )
                if not users or users[-1].get("job_id") != body.job_id or users[-1].get("status") != "failed":
                    raise AppError(
                        "REVISION_CONFLICT", "Send a new message to retry against the current video.", 409
                    )
                retry_message = users[-1]
            handle = self.submit_job(
                caller,
                StudioCommand(
                    project_id=project,
                    conversation_id=conversation,
                    idempotency_key="retry-job:" + body.job_id,
                    input=INPUTS[job["kind"]](**job["input"]),
                ),
                job["kind"],
            )

            def remember_retry(tx):
                current = tx.get(project_path(project, "jobs", body.job_id))
                current["retried_by"] = handle.job_id
                tx.set(project_path(project, "jobs", body.job_id), current)
                if retry_message:
                    set_message(
                        tx,
                        conversation_path(project, conversation),
                        {
                            **retry_message,
                            "status": "running",
                            "job_id": handle.job_id,
                            "caller": caller.model_dump(),
                        },
                    )

            self.repo.atomic(remember_retry)
            return DataResult(data=handle.model_dump())
        marker = (
            conversation_path(project, conversation)
            + "/retries/"
            + hashlib.sha256(body.idempotency_key.encode()).hexdigest()
        )
        previous = self.repo.get(marker)
        if previous:
            if previous["uid"] != caller.uid:
                raise AppError("IDEMPOTENCY_CONFLICT", "Retry belongs to another caller", 409)
            return DataResult(data=previous["result"])
        run_path = project_path(project, "runs", doc["active_run_id"]) if doc["active_run_id"] else None
        if not run_path:
            raise AppError("REVISION_CONFLICT", "There is no failed workflow to retry", 409)

        def claim(tx):
            run = tx.get(run_path)
            if run["status"] != "failed" and run.get("retry_owner") != body.idempotency_key:
                raise AppError("REVISION_CONFLICT", "Only a confirmed failed workflow can be retried", 409)
            jobs = [
                (key, self.repo.get(project_path(project, "jobs", jid)))
                for key, jid in run["workflow"]["children"].items()
            ]
            story = self.repo.get(project_path(project, "jobs", run["workflow"]["storyboard_job"]))
            jobs.append(("storyboard_job", story))
            if any(j and j["status"] == "submission_unknown" for _, j in jobs):
                raise AppError("REVISION_CONFLICT", "Uncertain submissions require reconciliation", 409)
            # With no failed job (e.g. the run stopped on a budget check), resuming is enough:
            # the scheduler's idempotent submissions reuse finished jobs.
            failures = [(key, job) for key, job in jobs if job and job["status"] == "failed"]
            run.update(
                status="waiting_for_jobs",
                retry_owner=body.idempotency_key,
                version=run["version"] + 1,
                error=None,
            )
            tx.set(run_path, run)
            self.project_run(tx, run)
            return run, failures

        run, failures = self.repo.atomic(claim)
        try:
            for key, job in failures:
                from tools.contracts.models import ImageCommand, ImageInput
                from tools.contracts.studio import INPUTS

                request = (ImageCommand if job["kind"] == "image" else StudioCommand)(
                    project_id=project,
                    conversation_id=conversation,
                    idempotency_key="retry:" + conversation + ":" + body.idempotency_key + ":" + key,
                    input=(ImageInput if job["kind"] == "image" else INPUTS[job["kind"]])(**job["input"]),
                )
                handle = self.submit_job(
                    caller,
                    request,
                    job["kind"],
                    parent_run=run["run_id"],
                    storyboard_override=job.get("storyboard_override"),
                )

                def link(tx, key=key, handle=handle):
                    current = tx.get(run_path)
                    if key == "storyboard_job":
                        current["workflow"][key] = handle.job_id
                    else:
                        current["workflow"]["children"][key] = handle.job_id
                    tx.set(run_path, current)

                self.repo.atomic(link)
        except AppError:

            def restore(tx):
                current = tx.get(run_path)
                current["status"] = "failed"
                tx.set(run_path, current)
                self.project_run(tx, current)

            self.repo.atomic(restore)
            raise
        result = {"run_id": run["run_id"], "status": "waiting_for_jobs"}

        def remember(tx):
            tx.set(marker, {"uid": caller.uid, "result": result})
            # Resubmitted jobs advance the run when they finish; a run with none resumes now.
            self.enqueue_advance(tx, project, "run", run["run_id"])

        self.repo.atomic(remember)
        return DataResult(data=result)


class ConversationScheduler:
    def __init__(self, commands):
        self.c = commands

    def sweep(self):
        """Recovery pass. Advance events handle normal progress, so this reads only conversations
        with an unfinished request or an unfinished run; idle projects cost no document reads."""
        from execution.dispatch import live_matches
        from tools.commands import project_path

        c = self.c
        waiting, candidates = set(), set()
        for message_path, _ in c.repo.group_where(
            "messages", "status", ["queued", "running", "needs_reconciliation"]
        ):
            parts = message_path.split("/")
            if len(parts) == 6 and parts[0] == "projects" and parts[2] == "conversations":
                waiting.add((parts[1], parts[3]))
        unfinished = ["queued", "running", "waiting_for_jobs", "needs_approval", "needs_reconciliation"]
        for pid, run in live_matches(c.repo, "runs", "status", unfinished):
            if run.get("conversation_id"):
                candidates.add((pid, run["conversation_id"]))
        candidates = sorted(candidates | waiting)
        if not candidates:
            return
        project_ids = sorted({pid for pid, _ in candidates})
        live = {
            pid
            for pid, project in zip(
                project_ids, c.repo.get_many([project_path(p) for p in project_ids]), strict=True
            )
            if project and not project.get("deleting")
        }
        candidates = [(pid, cid) for pid, cid in candidates if pid in live]
        docs = c.repo.get_many([conversation_path(pid, cid) for pid, cid in candidates])
        run_paths = sorted(
            {
                project_path(pid, "runs", d["active_run_id"])
                for (pid, _), d in zip(candidates, docs, strict=True)
                if d and d.get("active_run_id")
            }
        )
        runs = dict(zip(run_paths, c.repo.get_many(run_paths), strict=True))
        for (pid, cid), doc in zip(candidates, docs, strict=True):
            if not doc or doc.get("deleting"):
                continue
            active = (
                runs.get(project_path(pid, "runs", doc["active_run_id"]))
                if doc.get("active_run_id")
                else None
            )
            needs_sync = active and (
                doc.get("synced_run_id") != active["run_id"]
                or doc.get("synced_run_version") != active["version"]
            )
            if (pid, cid) in waiting or needs_sync:
                self.resume(pid, doc)

    def resume(self, pid, doc):
        """Advance one conversation under its lease, recording an application failure on its request.

        Returns False when another pass holds the lease, so an event can be redelivered.
        """
        from tools.commands import identifier

        c = self.c
        path = conversation_path(pid, doc["id"])
        try:
            owner = identifier("chat_scheduler")

            def claim(tx):
                latest = tx.get(path)
                if latest.get("lease_expiry", 0) > c.clock():
                    return False
                latest.update(lease_owner=owner, lease_expiry=c.clock() + 30)
                tx.set(path, latest)
                return True

            if not c.repo.atomic(claim):
                return False
            try:
                self.advance(pid, c.repo.get(path))
            except AppError as exc:
                pending = next(
                    (
                        m
                        for m in c.repo.list(path + "/messages")
                        if m.get("status") in {"queued", "running", "needs_reconciliation"}
                    ),
                    None,
                )
                if pending:

                    def record_error(tx, exc=exc):
                        set_message(
                            tx,
                            path,
                            {
                                **pending,
                                "status": "cancelled" if exc.payload.code == "ACCESS_DENIED" else "failed",
                            },
                        )
                        append_message(
                            c,
                            tx,
                            pid,
                            doc["id"],
                            "error:" + pending["id"],
                            "assistant",
                            exc.payload.message,
                            [{"kind": "error"}],
                        )
                        self.follow_up(tx, pid, doc["id"])

                    c.repo.atomic(record_error)
            finally:

                def release(tx):
                    latest = tx.get(path)
                    if latest.get("lease_owner") == owner:
                        latest["lease_expiry"] = 0
                        tx.set(path, latest)

                c.repo.atomic(release)
        except Exception:
            # A conversation erased mid-pass is skipped rather than stopping the worker.
            if c.repo.get(path) is None:
                return True
            raise
        return True

    def advance(self, project, doc):
        from tools.commands import project_path

        c = self.c
        path = conversation_path(project, doc["id"])
        messages = sorted(c.repo.list(path + "/messages"), key=lambda m: m["sequence"])
        active = (
            c.repo.get(project_path(project, "runs", doc["active_run_id"])) if doc["active_run_id"] else None
        )
        if active and (
            doc.get("synced_run_id") != active["run_id"] or doc.get("synced_run_version") != active["version"]
        ):
            self.sync(project, doc, active)

            def remember(tx):
                current = tx.get(path)
                if current["active_run_id"] == active["run_id"]:
                    current.update(synced_run_id=active["run_id"], synced_run_version=active["version"])
                    tx.set(path, current)

            c.repo.atomic(remember)
        pending = next(
            (m for m in messages if m.get("status") in {"queued", "running", "needs_reconciliation"}), None
        )
        if not pending:
            return
        caller = Caller(**pending["caller"])
        try:
            c.authorize(caller, project, GENERATE)
        except AppError:
            c.repo.atomic(lambda tx: set_message(tx, path, {**pending, "status": "cancelled"}))
            return
        scoped_jobs = c.repo.list_where(project_path(project, "jobs"), "conversation_id", [doc["id"]])
        if any(
            job["job_id"] != pending.get("job_id")
            and (job["status"] not in TERMINAL or job["status"] == "submission_unknown")
            for job in scoped_jobs
        ):
            return  # Serialize requests behind standalone edits/renders as well as scene production.
        if active:
            jobs = [c.repo.get(project_path(project, "jobs", jid)) for jid in active.get("job_ids", [])]
            if any(j and j["status"] not in TERMINAL for j in jobs):
                return  # Finish the current operation before applying a queued revision.
            if any(j and j["status"] == "submission_unknown" for j in jobs):
                return
            flow = active.get("workflow", {})
            sid = flow.get("current_scene_id")
            if sid and active["status"] not in {"failed", "cancelled", "succeeded"}:
                prepared_id = flow["children"].get(sid + ":prepared")
                prepared = c.repo.get(project_path(project, "jobs", prepared_id)) if prepared_id else None
                if not prepared or prepared["status"] not in TERMINAL:
                    return
        if not pending.get("job_id"):
            previous_story = (
                c.get_storyboard(caller, project, doc["storyboard_head"]).data
                if doc["storyboard_head"]
                else None
            )
            composition = (
                c.get_hyperframe(caller, project, doc["composition_head"], doc["id"]).data["manifest"][
                    "timeline"
                ]
                if doc["composition_head"]
                else None
            )
            request = pending["request"]
            context = {
                "history": [{"role": m["role"], "text": m["text"]} for m in messages[-12:]],
                "storyboard": previous_story,
                "composition": composition,
                "settings": request,
                "stage": active.get("workflow", {}).get("stage") if active else "idea",
            }
            handle = c.submit_job(
                caller,
                StudioCommand(
                    project_id=project,
                    conversation_id=doc["id"],
                    idempotency_key="turn:" + doc["id"] + ":" + pending["id"],
                    input=ConversationInput(
                        instruction=pending["text"],
                        context=context,
                        reference_artifact_ids=request["reference_artifact_ids"],
                        spend_cap_micros=request["spend_cap_micros"],
                    ),
                ),
                "director_turn",
            )
            c.repo.atomic(
                lambda tx: set_message(tx, path, {**pending, "job_id": handle.job_id, "status": "running"})
            )
            return
        job = c.repo.get(project_path(project, "jobs", pending["job_id"]))
        if job["status"] not in TERMINAL:
            return
        if job["status"] == "submission_unknown":
            if pending["status"] != "needs_reconciliation":
                c.repo.atomic(lambda tx: set_message(tx, path, {**pending, "status": "needs_reconciliation"}))
            return
        if job["status"] != "succeeded":

            def failure(tx):
                set_message(tx, path, {**pending, "status": job["status"]})
                append_message(
                    c,
                    tx,
                    project,
                    doc["id"],
                    "turn-failed:" + pending["id"] + ":" + job["job_id"],
                    "assistant",
                    job.get("error", {}).get("message", "The request could not be completed."),
                    [{"kind": "error", "job_id": job["job_id"], "retryable": job["status"] == "failed"}],
                )
                self.follow_up(tx, project, doc["id"])

            c.repo.atomic(failure)
            return
        output, _ = c.asset_content(caller, project, job["artifact_ids"][0])
        turn = DirectorTurn.model_validate_json(output)
        try:
            blocks = self.apply_turn(caller, project, doc, pending, turn, active)
        except AppError as exc:
            turn = DirectorTurn(text=exc.payload.message, action="clarify")
            blocks = []

        def complete(tx):
            set_message(tx, path, {**pending, "status": "succeeded"})
            append_message(c, tx, project, doc["id"], "turn:" + pending["id"], "assistant", turn.text, blocks)
            self.follow_up(tx, project, doc["id"])

        c.repo.atomic(complete)

    def follow_up(self, tx, project, conversation):
        """A finished request may leave another queued, and the active run pauses while requests are open."""
        self.c.enqueue_advance(tx, project, "conversation", conversation)
        active = tx.get(conversation_path(project, conversation)).get("active_run_id")
        if active:
            self.c.enqueue_advance(tx, project, "run", active)

    def apply_turn(self, caller, project, doc, message, turn, active):
        from tools.commands import project_path

        c = self.c
        preferences = message["request"].get("creative_preferences")
        if preferences is not None and turn.action not in {"storyboard", "clarify", "status"}:
            raise AppError("INVALID_INPUT", "Review a revised storyboard before changing style or motion.")
        if turn.action == "storyboard":
            plan = turn.storyboard
            if plan.project_id != project:
                raise AppError("INVALID_INPUT", "Director changed the project")
            return self.revise_plan(caller, project, doc, message, plan, active)
        if turn.action == "edit_composition":
            if not doc["composition_head"]:
                raise AppError("INVALID_INPUT", "Create the scenes before editing the combined video.")
            handle = c.submit_job(
                caller,
                StudioCommand(
                    project_id=project,
                    conversation_id=doc["id"],
                    idempotency_key="edit:" + message["id"] + doc["id"],
                    input=EditInput(expected_head=doc["composition_head"], instruction=turn.instruction),
                ),
                "edit",
            )
            return [{"kind": "progress", "job_id": handle.job_id}]
        if turn.action == "generate_scene":
            if not active or not doc["storyboard_head"]:
                raise AppError("INVALID_INPUT", "Write and approve a storyboard first.")
            plan = c.get_storyboard(caller, project, doc["storyboard_head"]).data
            if turn.scene_id not in {s["id"] for s in plan["scenes"]}:
                raise AppError("INVALID_INPUT", "Choose a scene in the current storyboard.")
            approval = (
                c.repo.get(project_path(project, "approvals", active.get("pending_approval_id")))
                if active.get("pending_approval_id")
                else None
            )
            if approval and approval["decision"] == "pending" and approval["kind"] in {"storyboard", "scene"}:
                return [{"kind": "review", **approval}]
            prepared_id = active.get("workflow", {}).get("children", {}).get(turn.scene_id + ":prepared")
            prepared = c.repo.get(project_path(project, "jobs", prepared_id)) if prepared_id else None
            if prepared and prepared["status"] == "succeeded":
                return self.revise_plan(
                    caller,
                    project,
                    doc,
                    message,
                    Storyboard.model_validate(plan),
                    active,
                    force_scene_ids={turn.scene_id},
                )
        return []

    def revise_plan(self, caller, project, doc, message, plan, active, force_scene_ids=None):
        from tools.commands import project_path

        c = self.c
        reused = {}
        preferences = message["request"].get("creative_preferences")
        if preferences is not None:
            plan.creative_preferences = CreativePreferences.model_validate(preferences)
        elif plan.creative_preferences is None and doc["storyboard_head"]:
            previous_preferences = c.get_storyboard(caller, project, doc["storyboard_head"]).data.get(
                "creative_preferences"
            )
            if previous_preferences:
                plan.creative_preferences = CreativePreferences.model_validate(previous_preferences)
        affected = set(force_scene_ids or ())
        if active and doc["storyboard_head"]:
            old = c.get_storyboard(caller, project, doc["storyboard_head"]).data
            previous = {s["id"]: s for s in old["scenes"]}
            affected = set(force_scene_ids or ())
            visual_fields = ("visual_prompt", "reference_artifact_ids", "continuity_from_scene_id")
            for scene in plan.scenes:
                before = previous.get(scene.id)
                if (
                    not before
                    or old["aspect_ratio"] != plan.aspect_ratio
                    or old.get("creative_preferences")
                    != (plan.creative_preferences.model_dump() if plan.creative_preferences else None)
                    or any(before[k] != getattr(scene, k) for k in visual_fields)
                ):
                    affected.add(scene.id)
            changed = True
            while changed:
                more = {s.id for s in plan.scenes if s.continuity_from_scene_id in affected}
                changed = not more <= affected
                affected |= more
            for key, jid in active["workflow"]["children"].items():
                if key in {"composition", "draft", "export"} or key.split(":")[0] in affected:
                    continue
                job = c.repo.get(project_path(project, "jobs", jid))
                if not job or job["status"] != "succeeded":
                    continue
                if key.startswith("music") and (
                    old["music"] != plan.music.model_dump()
                    # Raw music still covers a shorter video; only its trimmed copy must be redone.
                    or (
                        old["duration_seconds"] != plan.duration_seconds
                        if key == "music:prepared"
                        else plan.duration_seconds > old["duration_seconds"]
                    )
                ):
                    continue
                if ":" in key and key.split(":")[0] in previous:
                    scene = next((s for s in plan.scenes if s.id == key.split(":")[0]), None)
                    if not scene:
                        continue
                    if (
                        key.endswith(":prepared")
                        and previous[scene.id]["editorial_duration_seconds"]
                        != scene.editorial_duration_seconds
                    ):
                        continue
                    if key.endswith(":plate"):
                        aid = job["artifact_ids"][0]
                        if (
                            c._artifact(project, aid)["media"]["duration_seconds"]
                            < scene.editorial_duration_seconds
                        ):
                            continue
                reused[key] = jid
        handle = c.submit_job(
            caller,
            StudioCommand(
                project_id=project,
                conversation_id=doc["id"],
                idempotency_key="plan:" + doc["id"] + message["id"],
                input=BriefInput(
                    brief=doc["title"] if active else message["text"],
                    duration_seconds=plan.duration_seconds,
                    aspect_ratio=plan.aspect_ratio,
                    workflow_mode=message["request"].get("workflow_mode") or doc["workflow_mode"],
                    policy=message["request"].get("policy", "product_launch"),
                    spend_cap_micros=message["request"]["spend_cap_micros"],
                ),
            ),
            "storyboard",
            storyboard_override=plan.model_dump(),
            reused_children=reused,
        )

        def replace(tx):
            if active and active["run_id"] != handle.run_id:
                old_run = tx.get(project_path(project, "runs", active["run_id"]))
                old_run.update(status="cancelled", pending_approval_id=None, version=old_run["version"] + 1)
                tx.set(project_path(project, "runs", active["run_id"]), old_run)
                c.project_run(tx, old_run)
                for approval in c.repo.list(project_path(project, "approvals")):
                    if approval.get("run_id") == active["run_id"] and approval["decision"] == "pending":
                        tx.set(
                            project_path(project, "approvals", approval["id"]),
                            {**approval, "decision": "superseded"},
                        )
            replacement = tx.get(project_path(project, "runs", handle.run_id))
            replacement["workflow"]["affected_scene_ids"] = sorted(affected)
            tx.set(project_path(project, "runs", handle.run_id), replacement)
            current = tx.get(conversation_path(project, doc["id"]))
            current["active_run_id"] = handle.run_id
            tx.set(conversation_path(project, doc["id"]), current)

        c.repo.atomic(replace)
        return [{"kind": "progress", "job_id": handle.job_id}]

    def sync(self, project, doc, run):
        from tools.commands import project_path

        c = self.c
        flow = run.get("workflow", {})
        caller = Caller(**flow["caller"])
        c.authorize(caller, project)
        path = conversation_path(project, doc["id"])
        storyjob = c.repo.get(project_path(project, "jobs", flow["storyboard_job"]))
        if storyjob and storyjob["status"] == "succeeded":
            aid = storyjob["artifact_ids"][0]
            plan = c.get_storyboard(caller, project, aid).data

            def story(tx):
                current = tx.get(path)
                current["storyboard_head"] = aid
                tx.set(path, current)
                append_message(
                    c,
                    tx,
                    project,
                    doc["id"],
                    "story:" + aid,
                    "assistant",
                    "Here’s your storyboard. You can change it in chat before creating any scenes.",
                    [{"kind": "storyboard", "artifact_id": aid, "storyboard": plan}],
                )

            c.repo.atomic(story)
            for scene in plan["scenes"]:
                jid = flow["children"].get(scene["id"] + ":prepared")
                job = c.repo.get(project_path(project, "jobs", jid)) if jid else None
                if job and job["status"] == "succeeded":
                    aid = job["artifact_ids"][0]
                    c.repo.atomic(
                        lambda tx, aid=aid, scene=scene: append_message(
                            c,
                            tx,
                            project,
                            doc["id"],
                            "scene:" + aid + ":" + storyjob["artifact_ids"][0],
                            "assistant",
                            scene["objective"],
                            [
                                {
                                    "kind": "scene",
                                    "scene_id": scene["id"],
                                    "artifact_id": aid,
                                    "storyboard_artifact_id": storyjob["artifact_ids"][0],
                                    "copy": scene["exact_copy"],
                                }
                            ],
                        )
                    )
        if flow.get("draft_artifact_id"):
            aid = flow["draft_artifact_id"]
            c.repo.atomic(
                lambda tx: append_message(
                    c,
                    tx,
                    project,
                    doc["id"],
                    "draft:" + aid,
                    "assistant",
                    "Your scenes are together. Review the video here, or open the timeline to fine-tune it.",
                    [
                        {
                            "kind": "video",
                            "artifact_id": aid,
                            "composition_artifact_id": flow["composition_artifact_id"],
                        }
                    ],
                )
            )
        if flow.get("export_artifact_id"):
            aid = flow["export_artifact_id"]
            c.repo.atomic(
                lambda tx: append_message(
                    c,
                    tx,
                    project,
                    doc["id"],
                    "export:" + aid,
                    "assistant",
                    "Your video is ready to download.",
                    [{"kind": "export", "artifact_id": aid}],
                )
            )
