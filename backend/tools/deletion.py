"""Permanent erasure of projects, conversations and storyboard scenes."""

import hashlib

from tools.contracts.errors import AppError
from tools.contracts.models import GENERATE, DataResult
from tools.contracts.studio import Storyboard
from tools.conversations import ConversationScheduler, append_message, conversation_path

UNSUBMITTED = {"queued", "claimed"}


class DeletionCommands:
    def _release(self, project, job_id):
        """Settle a reservation the worker can no longer settle once its job is erased."""
        from tools.commands import project_path

        def apply(tx):
            entry = tx.get("budgets/" + project + "/entries/" + job_id)
            job = tx.get(project_path(project, "jobs", job_id))
            if not entry or not job or entry["status"] == "settled":
                return
            # Past submission the provider may already bill; charge the reservation conservatively.
            amount = 0 if job["status"] in UNSUBMITTED else entry["reserved_micros"]
            self.settle(tx, job, amount, "erased_before_settlement" if amount else "not_submitted", {})

        self.repo.atomic(apply)

    def _erase_sessions(self, project, run_ids=None):
        """ADK sessions hold the director's copy of the chat history."""
        for session in self.repo.list_where("adk_sessions", "project_id", [project]):
            if run_ids is not None and (session.get("state") or {}).get("run_id") not in run_ids:
                continue
            key = f"{session['app_name']}:{project}:{session['user_id']}:{session['id']}"
            self.repo.delete_tree("adk_sessions/" + hashlib.sha256(key.encode()).hexdigest())

    def delete_project(self, caller, project):
        from tools.commands import project_path

        if caller.projects is not None:
            raise AppError("ACCESS_DENIED", "Delete projects with Firebase app authentication", 403)
        doc = self.authorize(caller, project, GENERATE, deleting_ok=True)
        if doc["members"].get(caller.uid) != "owner":
            raise AppError("ACCESS_DENIED", "Only the project owner can delete it", 403)

        def hide(tx):
            current = tx.get(project_path(project))
            current["deleting"] = True
            tx.set(project_path(project), current)

        self.repo.atomic(hide)
        for entry in self.repo.list_where(
            "budgets/" + project + "/entries", "status", ["reserved", "uncertain"]
        ):
            self._release(project, entry["job_id"])
        self._erase_sessions(project)
        self.repo.delete_tree("adk_app_state/" + project)
        for uid in doc["members"]:
            self.repo.delete_tree("adk_user_state/" + project + "_" + uid)
        self.storage.delete_prefix(f"projects/{project}/")
        self.repo.delete_tree("budgets/" + project)
        self.repo.delete_tree(project_path(project))
        return DataResult(data={"deleted": project})

    def delete_conversation(self, caller, project, conversation):
        from tools.commands import project_path

        self.authorize(caller, project, GENERATE)
        path = conversation_path(project, conversation)
        if not self.repo.get(path):
            raise AppError("NOT_FOUND", "Conversation not found", 404)

        def hide(tx):
            current = tx.get(path)
            current["deleting"] = True
            tx.set(path, current)

        self.repo.atomic(hide)
        runs = self.repo.list_where(project_path(project, "runs"), "conversation_id", [conversation])
        run_ids = {run["run_id"] for run in runs}
        # Stop the scheduler from submitting further work for these runs while they are erased.
        for run_id in run_ids:

            def stop(tx, run_id=run_id):
                run = tx.get(project_path(project, "runs", run_id))
                if run and run["status"] not in {"succeeded", "failed", "cancelled"}:
                    run.update(status="cancelled", version=run["version"] + 1)
                    tx.set(project_path(project, "runs", run_id), run)

            self.repo.atomic(stop)
        jobs = {
            job["job_id"]: job
            for job in self.repo.list_where(project_path(project, "jobs"), "conversation_id", [conversation])
        }
        for run in runs:
            for job_id in run.get("job_ids", [run["job_id"]]):
                if job_id not in jobs:
                    job = self.repo.get(project_path(project, "jobs", job_id))
                    if job:
                        jobs[job_id] = job

        # Media still referenced by other videos, the project head or surviving artifacts is kept.
        produced = {"art_" + job_id.removeprefix("job_"): job_id for job_id in jobs}
        artifacts = {a["id"]: a for a in self.repo.list(project_path(project, "artifacts"))}
        roots = [a for a in artifacts if a not in produced]
        roots.append((self.repo.get(project_path(project)) or {}).get("composition_head"))
        for other in self.repo.list(project_path(project, "conversations")):
            if other["id"] != conversation:
                roots += [other.get("composition_head"), other.get("storyboard_head")]
        keep, stack = set(), [r for r in roots if r]
        while stack:
            artifact_id = stack.pop()
            if artifact_id not in keep:
                keep.add(artifact_id)
                stack.extend(artifacts.get(artifact_id, {}).get("input_artifact_ids") or [])

        for artifact_id, job_id in produced.items():
            if artifact_id in keep:
                self.repo.atomic(
                    lambda tx, job_id=job_id: tx.set(
                        project_path(project, "jobs", job_id),
                        {**tx.get(project_path(project, "jobs", job_id)), "conversation_id": None},
                    )
                )
                continue
            self._release(project, job_id)
            job = jobs[job_id]
            doomed = [
                project_path(project, "jobs", job_id),
                project_path(project, "outbox", job_id),
                project_path(project, "reconciliations", job_id),
                project_path(project, "steps", job["step_id"]),
                project_path(project, "artifacts", artifact_id),
                project_path(project, "artifact_lifecycle", artifact_id),
                project_path(project, "approved_compositions", artifact_id),
                "budgets/" + project + "/entries/" + job_id,
            ]
            self.repo.atomic(lambda tx, doomed=doomed: [tx.delete(p) for p in doomed])
            self.storage.delete_prefix(f"projects/{project}/jobs/{job_id}/")

        doomed = [project_path(project, "runs", r) for r in run_ids]
        doomed += [project_path(project, "run_summaries", r) for r in run_ids]
        doomed += [
            project_path(project, "approvals", a["id"])
            for a in self.repo.list(project_path(project, "approvals"))
            if a.get("conversation_id") == conversation or a.get("run_id") in run_ids
        ]
        ordered = sorted(run_ids)
        for start in range(0, len(ordered), 30):  # Firestore "in" filters accept 30 values.
            events = self.repo.list_where(
                project_path(project, "events"), "run_id", ordered[start : start + 30]
            )
            doomed += [project_path(project, "events", f"{e['run_id']}_{e['sequence']:012d}") for e in events]
        for start in range(0, len(doomed), 400):  # Stay below Firestore's 500-write transaction limit.
            self.repo.atomic(lambda tx, chunk=doomed[start : start + 400]: [tx.delete(p) for p in chunk])
        self._erase_sessions(project, run_ids)
        self.repo.delete_tree(path)
        return DataResult(data={"deleted": conversation})

    def remove_scene(self, caller, project, conversation, scene_id, idempotency_key):
        """Drop one storyboard scene; the video shortens and unaffected scene media is reused."""
        from tools.commands import project_path

        doc = self.conversation(caller, project, conversation, scope=GENERATE)
        path = conversation_path(project, conversation)

        def marker(source):
            return self.repo.get(path + "/message_keys/" + hashlib.sha256(source.encode()).hexdigest())

        # A retried request returns the original outcome, or finishes a removal interrupted midway.
        started, done = (
            marker("remove-scene:" + idempotency_key),
            marker("remove-scene-done:" + idempotency_key),
        )
        if started and done:
            return DataResult(data=self.repo.get(path + "/messages/" + started["id"])["removal"])
        if not doc["storyboard_head"]:
            raise AppError("INVALID_INPUT", "This video has no storyboard yet")
        busy = self.repo.list_where(path + "/messages", "status", ["queued", "running"])
        active = (
            self.repo.get(project_path(project, "runs", doc["active_run_id"]))
            if doc["active_run_id"]
            else None
        )
        if not started and (
            busy
            or (
                active
                and any(
                    job and job["status"] not in {"succeeded", "failed", "cancelled"}
                    for job in (
                        self.repo.get(project_path(project, "jobs", j)) for j in active.get("job_ids", [])
                    )
                )
            )
        ):
            raise AppError(
                "REVISION_CONFLICT",
                "Wait for the current step to finish or stop it, then delete the scene",
                409,
            )
        plan = self.get_storyboard(caller, project, doc["storyboard_head"]).data
        scenes = [s for s in plan["scenes"] if s["id"] != scene_id]
        if len(scenes) == len(plan["scenes"]):
            raise AppError("INVALID_INPUT", "Choose a scene in the current storyboard")
        if len(scenes) < 3:
            raise AppError("INVALID_INPUT", "A storyboard needs at least 3 scenes")
        for scene in scenes:
            if scene.get("continuity_from_scene_id") == scene_id:
                scene["continuity_from_scene_id"] = None
        duration = round(sum(s["editorial_duration_seconds"] for s in scenes), 3)
        if duration < 6:
            raise AppError("INVALID_INPUT", "The video would be shorter than 6 seconds")
        revised = Storyboard.model_validate({**plan, "scenes": scenes, "duration_seconds": duration})
        removed = next(s for s in plan["scenes"] if s["id"] == scene_id)
        label = f"scene {plan['scenes'].index(removed) + 1} ({removed['objective']})"
        removal = {"removed": scene_id, "duration_seconds": duration}

        message = self.repo.atomic(
            lambda tx: append_message(
                self,
                tx,
                project,
                conversation,
                "remove-scene:" + idempotency_key,
                "user",
                "Delete " + label,
                status="succeeded",
                request={"spend_cap_micros": None},
                uid=caller.uid,
                removal=removal,
            )
        )
        blocks = ConversationScheduler(self).revise_plan(caller, project, doc, message, revised, active)
        self.repo.atomic(
            lambda tx: append_message(
                self,
                tx,
                project,
                conversation,
                "remove-scene-done:" + idempotency_key,
                "assistant",
                f"Removed {label}. Your video is now {duration:g}s; the remaining scenes are reused.",
                blocks,
            )
        )
        return DataResult(data=removal)
