"""Durable dependency scheduler. No resident director or creative planning loop."""

from execution.telemetry import event
from tools.commands import identifier, project_path
from tools.contracts.errors import AppError
from tools.contracts.models import Caller, ImageCommand, ImageInput
from tools.contracts.studio import (
    Clip,
    Composition,
    FrameInput,
    PrepareInput,
    RenderInput,
    StudioCommand,
    VideoInput,
)
from tools.conversations import ConversationScheduler, conversation_path, head_path


class WorkflowScheduler:
    def __init__(self, commands):
        self.commands = commands

    def sweep(self):
        from execution.dispatch import live_matches

        ConversationScheduler(self.commands).sweep()
        active = ["queued", "running", "waiting_for_jobs"]
        for project_id, run in live_matches(self.commands.repo, "runs", "status", active):
            self.resume(project_id, run)

    def resume(self, project_id, run):
        """Advance one workflow run, recording an application failure on the run.

        Returns False when another pass holds the run's lease, so an event can be redelivered.
        """
        if not run.get("workflow") or run["status"] in {
            "cancelled",
            "failed",
            "succeeded",
            "needs_reconciliation",
        }:
            return True
        try:
            return self.advance(project_id, run["run_id"])
        except Exception as exc:
            # A run erased mid-pass is skipped rather than stopping the worker.
            if not self.commands.repo.get(project_path(project_id, "runs", run["run_id"])):
                return True
            if not isinstance(exc, AppError):
                raise
            if exc.payload.code == "STALE_SCHEDULER":
                return True
            event("run_failed", run_id=run["run_id"], code=exc.payload.code, message=exc.payload.message)
            self.change(
                project_id,
                run["run_id"],
                status="failed",
                error=exc.payload.model_dump(),
            )
            return True

    def change(self, project, run_id, *, owner=None, **values):
        def apply(tx):
            path = project_path(project, "runs", run_id)
            run = tx.get(path)
            if run["status"] == "cancelled":
                return
            if owner and (
                run.get("scheduler_owner") != owner or run.get("scheduler_expiry", 0) <= self.commands.clock()
            ):
                raise AppError("STALE_SCHEDULER", "Scheduler lease expired", 409)
            if all(run.get(key) == value for key, value in values.items()):
                return
            run.update(values)
            run["version"] += 1
            tx.set(path, run)
            self.commands.project_run(tx, run)
            if run.get("conversation_id"):
                self.commands.enqueue_advance(tx, project, "conversation", run["conversation_id"])
            tx.set(
                project_path(project, "events", f"{run_id}_{run['version']:012d}"),
                {
                    "run_id": run_id,
                    "sequence": run["version"],
                    "status": run["status"],
                    "created_at": self.commands.clock(),
                },
            )

        self.commands.repo.atomic(apply)

    def approval(self, project, run_id, kind, target, *, owner=None, storyboard_id=None, scene_id=None):
        def apply(tx):
            path = project_path(project, "runs", run_id)
            run = tx.get(path)
            if run["status"] in {"cancelled", "failed", "needs_reconciliation"}:
                return False
            if owner and (
                run.get("scheduler_owner") != owner or run.get("scheduler_expiry", 0) <= self.commands.clock()
            ):
                raise AppError("STALE_SCHEDULER", "Scheduler lease expired", 409)
            approval_id = (
                "approval_"
                + target.removeprefix("art_")
                + "_"
                + kind
                + ("_" + storyboard_id.removeprefix("art_") if storyboard_id else "")
            )
            apath = project_path(project, "approvals", approval_id)
            approval = tx.get(apath)
            if not approval:
                approval = {
                    "id": approval_id,
                    "kind": kind,
                    "conversation_id": run.get("conversation_id"),
                    "storyboard_artifact_id": storyboard_id,
                    "scene_id": scene_id,
                    "run_id": run_id,
                    "target_artifact_id": target,
                    "decision": "pending",
                    "created_at": self.commands.clock(),
                    "review_url": f"{self.commands.settings.web_url}/projects/{project}",
                }
                tx.set(apath, approval)
            if approval["decision"] == "pending":
                if run["status"] == "needs_approval" and run.get("pending_approval_id") == approval_id:
                    return False
                run.update(status="needs_approval", pending_approval_id=approval_id)
                run["version"] += 1
                tx.set(path, run)
                self.commands.project_run(tx, run)
                if run.get("conversation_id"):
                    self.commands.enqueue_advance(tx, project, "conversation", run["conversation_id"])
                return False
            return approval["decision"] == "approved"

        return self.commands.repo.atomic(apply)

    def advance(self, project, run_id):
        """One scheduler pass. Returns False only when another pass holds the run's lease."""
        current = self.commands.repo.get(project_path(project, "runs", run_id))
        if not current or current["status"] in {"cancelled", "failed", "succeeded"}:
            return True
        conversation = (
            self.commands.repo.get(conversation_path(project, current["conversation_id"]))
            if current.get("conversation_id")
            else None
        )
        pending = (
            self.commands.repo.query(
                conversation_path(project, current["conversation_id"]) + "/messages",
                filters=[("status", "in", ["queued", "running"])],
                limit=1,
            )
            if conversation
            else []
        )
        # Nothing that a pass reads has changed since the last one, so skip its lease transaction.
        signature = [
            current["version"],
            conversation.get("sequence", 0) if conversation else 0,
            bool(pending),
        ]
        if current.get("scheduler_seen") == signature:
            return True
        owner = identifier("scheduler")
        busy = object()

        def claim(tx):
            path = project_path(project, "runs", run_id)
            run = tx.get(path)
            if not run or run["status"] in {"cancelled", "failed", "succeeded"}:
                return None
            if run.get("scheduler_expiry", 0) > self.commands.clock():
                return busy
            # One pass makes many sequential Firestore round trips (~40 s for a few scenes over a
            # transcontinental link). A lease shorter than the pass makes its final save stale and
            # silently drops every child it linked. The lease is released when the pass ends.
            run.update(scheduler_owner=owner, scheduler_expiry=self.commands.clock() + 300)
            tx.set(path, run)
            return run

        run = self.commands.repo.atomic(claim)
        if run is busy:
            return False
        if not run:
            return True
        try:
            self._advance(project, run)
            return True
        except Exception as exc:
            if not (isinstance(exc, AppError) and exc.payload.code == "STALE_SCHEDULER"):
                # Children submitted earlier in this pass live only in run["workflow"]; keep them
                # linked so their media still appears even though the pass failed.
                self.change(project, run_id, workflow=run["workflow"])
            raise
        finally:

            def release(tx):
                path = project_path(project, "runs", run_id)
                current = tx.get(path)
                if current and current.get("scheduler_owner") == owner:
                    current["scheduler_expiry"] = 0
                    current["scheduler_seen"] = signature
                    tx.set(path, current)

            self.commands.repo.atomic(release)

    def _advance(self, project, run):
        def change(*args, **kwargs):
            return self.change(*args, owner=run["scheduler_owner"], **kwargs)

        c = self.commands
        flow = run["workflow"]
        run_id = run["run_id"]
        caller = Caller(**flow["caller"])
        c.authorize(caller, project, "vibeshorts:generate")
        children = flow["children"]
        cid = run.get("conversation_id")
        queued_changes = False
        if cid:
            conversation = c.repo.get(conversation_path(project, cid))
            if conversation.get("active_run_id") != run_id:
                change(project, run_id, status="cancelled")
                return
            queued_changes = bool(
                c.repo.query(
                    conversation_path(project, cid) + "/messages",
                    filters=[("status", "in", ["queued", "running"])],
                    limit=1,
                )
            )
            if queued_changes and not (flow.get("mode") == "guided" and flow.get("current_scene_id")):
                return

        def job(key):
            job_id = children.get(key)
            return c.repo.get(project_path(project, "jobs", job_id)) if job_id else None

        def result(key):
            value = job(key)
            if not value:
                return None
            if value["status"] == "submission_unknown":
                change(project, run_id, status="needs_reconciliation")
                return None
            if value["status"] in {"failed", "cancelled"}:
                raise AppError(
                    "CHILD_JOB_FAILED",
                    "A production step failed; inspect its job before submitting a revision",
                    409,
                )
            return value["artifact_ids"][0] if value["status"] == "succeeded" else None

        def submit(key, kind, value):
            if key in children:
                return
            request = (ImageCommand if kind == "image" else StudioCommand)(
                project_id=project,
                conversation_id=run.get("conversation_id"),
                idempotency_key=run_id + ":" + key,
                input=value,
            )
            handle = c.submit_job(caller, request, kind, parent_run=run_id)
            children[key] = handle.job_id

        storyjob = c.repo.get(project_path(project, "jobs", flow["storyboard_job"]))
        if storyjob["status"] in {"failed", "cancelled"}:
            raise AppError("DIRECTOR_FAILED", "Storyboard generation failed")
        if storyjob["status"] == "submission_unknown":
            change(project, run_id, status="needs_reconciliation")
            return
        if storyjob["status"] != "succeeded":
            return
        story_id = storyjob["artifact_ids"][0]
        flow["storyboard_artifact_id"] = story_id
        if not self.approval(project, run_id, "storyboard", story_id, owner=run["scheduler_owner"]):
            change(project, run_id, workflow=flow)
            return
        plan = c.get_storyboard(caller, project, story_id).data
        flow["storyboard_artifact_id"] = story_id
        flow["stage"] = "production"
        from tools.contracts.studio import MusicInput

        submit("music", "music", MusicInput(**plan["music"]))
        guided = flow.get("mode") == "guided"
        for scene in plan["scenes"]:
            if guided:
                completed = result(scene["id"] + ":prepared")
                if completed:
                    if queued_changes:
                        change(project, run_id, workflow=flow)
                        return
                    if self.approval(
                        project,
                        run_id,
                        "scene",
                        completed,
                        owner=run["scheduler_owner"],
                        storyboard_id=story_id,
                        scene_id=scene["id"],
                    ):
                        continue
                    change(project, run_id, workflow=flow)
                    return
            sid = scene["id"]
            if guided:
                if queued_changes and flow.get("current_scene_id") != sid:
                    change(project, run_id, workflow=flow)
                    return
                flow["current_scene_id"] = sid
            duration = scene["editorial_duration_seconds"]
            preferences = plan.get("creative_preferences") or {}
            visual_prompt = scene["visual_prompt"]
            if preferences.get("vibe"):
                visual_prompt += ". Visual style: " + preferences["vibe"] + "."
            motion_prompt = visual_prompt
            if preferences.get("motion") == "slow_motion":
                motion_prompt += " Slow motion action and gentle, deliberate camera movement."

            anchor = None
            predecessor = scene.get("continuity_from_scene_id")
            if predecessor:
                previous = result(predecessor + ":prepared")
                if not previous:
                    if guided:
                        change(project, run_id, workflow=flow, status="waiting_for_jobs")
                        return
                    continue
                previous_facts = c._artifact(project, previous)["media"]
                submit(
                    sid + ":anchor",
                    "frame",
                    FrameInput(
                        artifact_id=previous,
                        frame_index=max(
                            0, round(previous_facts["duration_seconds"] * previous_facts["fps"]) - 1
                        ),
                    ),
                )
                anchor = result(sid + ":anchor")
                if not anchor:
                    if guided:
                        change(project, run_id, workflow=flow, status="waiting_for_jobs")
                        return
                    continue
            else:
                submit(
                    sid + ":keyframe",
                    "image",
                    ImageInput(
                        # Without this, image models treat references as loose inspiration.
                        prompt=(
                            "Use the attached reference image(s) as the exact subject: keep its shape, "
                            "colours, materials, markings and identifying details unchanged. "
                            if scene["reference_artifact_ids"]
                            else ""
                        )
                        + visual_prompt,
                        aspect_ratio=plan["aspect_ratio"],
                        reference_artifact_ids=scene["reference_artifact_ids"],
                    ),
                )
                anchor = result(sid + ":keyframe")
                if not anchor:
                    if guided:
                        change(project, run_id, workflow=flow, status="waiting_for_jobs")
                        return
                    continue
            source = next(d for d in (4, 6, 8) if d >= duration)
            submit(
                sid + ":plate",
                "video",
                VideoInput(
                    prompt=motion_prompt,
                    first_frame_artifact_id=anchor,
                    aspect_ratio=plan["aspect_ratio"],
                    source_duration_seconds=source,
                    generate_audio=c.settings.video_generate_audio,
                ),
            )
            plate = result(sid + ":plate")
            if plate:
                submit(
                    sid + ":prepared",
                    "prepare",
                    PrepareInput(artifact_id=plate, out_seconds=duration, aspect_ratio=plan["aspect_ratio"]),
                )
            if guided:
                change(project, run_id, workflow=flow, status="waiting_for_jobs")
                return
        music = result("music")
        if music:
            submit(
                "music:prepared",
                "prepare",
                PrepareInput(artifact_id=music, out_seconds=plan["duration_seconds"]),
            )
        prepared = [result(scene["id"] + ":prepared") for scene in plan["scenes"]]
        prepared_music = result("music:prepared")
        if all(prepared) and prepared_music:
            clips = []
            start = 0
            for scene, asset in zip(plan["scenes"], prepared, strict=True):
                duration = scene["editorial_duration_seconds"]
                sid = scene["id"]
                clips.append(
                    Clip(
                        id=sid + "-plate",
                        artifact_id=asset,
                        kind="video",
                        track=0,
                        start=start,
                        duration=duration,
                    )
                )
                clips.append(
                    Clip(
                        id=sid + "-text",
                        kind="text",
                        track=2,
                        start=start,
                        duration=duration,
                        text=" ".join(scene["exact_copy"]),
                    )
                )
                start += duration
            clips.append(
                Clip(
                    id="music",
                    artifact_id=prepared_music,
                    kind="audio",
                    track=1,
                    start=0,
                    duration=plan["duration_seconds"],
                    volume=0.8,
                    fade_in=0.4,
                    fade_out=0.7,
                )
            )
            brand = (
                c.repo.get(project_path(project, "brands", run["brand_version"]))
                if run["brand_version"]
                else None
            )
            if brand and brand.get("logo"):
                clips.append(
                    Clip(
                        id="brand-logo",
                        artifact_id=brand["logo"],
                        kind="image",
                        track=3,
                        start=max(0, start - 3),
                        duration=min(3, start),
                    )
                )
            project_doc = c.repo.get(head_path(project, run.get("conversation_id")))
            spec = Composition(
                title=flow["brief"]["brief"][:100],
                aspect_ratio=plan["aspect_ratio"],
                duration_seconds=plan["duration_seconds"],
                clips=clips,
                fonts=(brand or {}).get("fonts", {}),
                accent=(brand or {}).get("colors", {}).get("primary", "#bf96f6"),
                expected_head=project_doc.get("composition_head"),
            )
            submit("composition", "composition", spec)
        composition = result("composition")
        if composition:
            flow["composition_artifact_id"] = composition
            submit("draft", "render", RenderInput(composition_artifact_id=composition))
        draft = result("draft")
        if draft:
            flow["draft_artifact_id"] = draft
            flow["stage"] = "preview"
            if self.approval(project, run_id, "preview", composition, owner=run["scheduler_owner"]):
                submit("export", "render", RenderInput(composition_artifact_id=composition, quality="final"))
                export = result("export")
                if export:
                    flow["export_artifact_id"] = export
                    flow["stage"] = "complete"
                    change(project, run_id, status="succeeded", workflow=flow)
                    return
        latest = c.repo.get(project_path(project, "runs", run_id))
        change(
            project,
            run_id,
            workflow=flow,
            status=latest["status"]
            if latest["status"] in {"needs_approval", "needs_reconciliation"}
            else "waiting_for_jobs",
        )
