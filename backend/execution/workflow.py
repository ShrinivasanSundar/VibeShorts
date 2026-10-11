"""Durable dependency scheduler. No resident director or creative planning loop."""

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


class WorkflowScheduler:
    def __init__(self, commands):
        self.commands = commands

    def sweep(self):
        for project in self.commands.repo.list("projects"):
            if not project.get("project_id"):
                continue
            for run in self.commands.repo.list(project_path(project["project_id"], "runs")):
                if run.get("workflow") and run["status"] not in {
                    "cancelled",
                    "failed",
                    "succeeded",
                    "needs_reconciliation",
                }:
                    try:
                        self.advance(project["project_id"], run["run_id"])
                    except AppError as exc:
                        if exc.payload.code == "STALE_SCHEDULER":
                            continue
                        self.change(
                            project["project_id"],
                            run["run_id"],
                            status="failed",
                            error=exc.payload.model_dump(),
                        )

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
            run.update(values)
            run["version"] += 1
            tx.set(path, run)
            self.commands.project_run(tx, run)
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

    def approval(self, project, run_id, kind, target, *, owner=None):
        def apply(tx):
            path = project_path(project, "runs", run_id)
            run = tx.get(path)
            if run["status"] in {"cancelled", "failed", "needs_reconciliation"}:
                return False
            if owner and (
                run.get("scheduler_owner") != owner or run.get("scheduler_expiry", 0) <= self.commands.clock()
            ):
                raise AppError("STALE_SCHEDULER", "Scheduler lease expired", 409)
            approval_id = "approval_" + target.removeprefix("art_") + "_" + kind
            apath = project_path(project, "approvals", approval_id)
            approval = tx.get(apath)
            if not approval:
                approval = {
                    "id": approval_id,
                    "kind": kind,
                    "run_id": run_id,
                    "target_artifact_id": target,
                    "decision": "pending",
                    "created_at": self.commands.clock(),
                    "review_url": f"{self.commands.settings.web_url}/projects/{project}",
                }
                tx.set(apath, approval)
            if approval["decision"] == "pending":
                run.update(status="needs_approval", pending_approval_id=approval_id)
                run["version"] += 1
                tx.set(path, run)
                self.commands.project_run(tx, run)
                return False
            return approval["decision"] == "approved"

        return self.commands.repo.atomic(apply)

    def advance(self, project, run_id):
        owner = identifier("scheduler")

        def claim(tx):
            path = project_path(project, "runs", run_id)
            run = tx.get(path)
            if (
                run["status"] in {"cancelled", "failed", "succeeded"}
                or run.get("scheduler_expiry", 0) > self.commands.clock()
            ):
                return None
            run.update(scheduler_owner=owner, scheduler_expiry=self.commands.clock() + 30)
            tx.set(path, run)
            return run

        run = self.commands.repo.atomic(claim)
        if not run:
            return
        try:
            self._advance(project, run)
        finally:

            def release(tx):
                path = project_path(project, "runs", run_id)
                current = tx.get(path)
                if current.get("scheduler_owner") == owner:
                    current["scheduler_expiry"] = 0
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
                project_id=project, idempotency_key=run_id + ":" + key, input=value
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
        if not self.approval(project, run_id, "storyboard", story_id, owner=run["scheduler_owner"]):
            return
        plan = c.get_storyboard(caller, project, story_id).data
        flow["storyboard_artifact_id"] = story_id
        flow["stage"] = "production"
        from tools.contracts.studio import MusicInput

        submit("music", "music", MusicInput(**plan["music"]))
        for scene in plan["scenes"]:
            sid = scene["id"]
            duration = scene["editorial_duration_seconds"]
            anchor = None
            predecessor = scene.get("continuity_from_scene_id")
            if predecessor:
                previous = result(predecessor + ":prepared")
                if not previous:
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
                    continue
            else:
                submit(
                    sid + ":keyframe",
                    "image",
                    ImageInput(
                        prompt=scene["visual_prompt"],
                        aspect_ratio=plan["aspect_ratio"],
                        reference_artifact_ids=scene["reference_artifact_ids"],
                    ),
                )
                anchor = result(sid + ":keyframe")
                if not anchor:
                    continue
            source = next(d for d in (4, 6, 8) if d >= duration)
            submit(
                sid + ":plate",
                "video",
                VideoInput(
                    prompt=scene["visual_prompt"],
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
            project_doc = c.repo.get(project_path(project))
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
