from tools.composition.package import unpack
from tools.contracts.errors import AppError
from tools.contracts.models import GENERATE, DataResult, JobResult


def input_ids(kind, value):
    ids = list(value.reference_artifact_ids)
    for key in ("first_frame_artifact_id", "artifact_id", "composition_artifact_id"):
        if getattr(value, key, None):
            ids.append(getattr(value, key))
    if kind == "edit":
        ids.append(value.expected_head)
    if kind == "composition":
        ids.extend(c.artifact_id for c in value.clips if c.artifact_id)
        ids.extend(value.fonts.values())
    return list(dict.fromkeys(ids))


def validate_submission(commands, caller, project_id, kind, value, tx=None):
    from tools.commands import project_path

    tx = tx or commands.repo
    commands.authorize(caller, project_id, GENERATE, tx)
    for artifact_id in input_ids(kind, value):
        artifact = commands._artifact(project_id, artifact_id, tx)
        if kind in {"image", "storyboard"} and artifact["type"] != "image":
            raise AppError("INVALID_INPUT", "References must be image artifacts")
        if kind == "video" and artifact["type"] != "image":
            raise AppError("INVALID_INPUT", "Video first frame must be an image")
        if kind in {"prepare", "frame"} and artifact["type"] not in {"video", "audio", "render"}:
            raise AppError("INVALID_INPUT", "Preparation requires video or audio")
        if kind == "composition":
            if artifact_id in value.fonts.values() and artifact["type"] != "font":
                raise AppError("INVALID_INPUT", "Font references require decoded font artifacts")
            for clip in value.clips:
                if clip.artifact_id != artifact_id:
                    continue
                actual = (
                    "video"
                    if artifact["type"] == "render"
                    else "audio"
                    if clip.kind == "audio"
                    else clip.kind
                )
                if ("video" if artifact["type"] == "render" else artifact["type"]) != actual:
                    raise AppError("INVALID_INPUT", "Clip type does not match artifact")
                if clip.kind == "video" and clip.volume > 0 and not artifact["media"].get("has_audio"):
                    raise AppError("INVALID_INPUT", "This video has no audio stream")
                duration = artifact["media"].get("duration_seconds")
                if duration and clip.source_in + clip.duration > duration + 0.05:
                    raise AppError("INVALID_INPUT", "Clip exceeds the source duration")
    if kind == "storyboard" and value.revision_of_run_id:
        project = tx.get(project_path(project_id))
        if project.get("composition_head") != value.expected_head:
            raise AppError("REVISION_CONFLICT", "Composition head advanced", 409)
    if kind in {"composition", "edit"}:
        project = tx.get(project_path(project_id))
        if project.get("composition_head") != value.expected_head:
            raise AppError("REVISION_CONFLICT", "Composition head advanced", 409)
    if kind == "render":
        artifact = commands._artifact(project_id, value.composition_artifact_id, tx)
        if artifact["type"] != "composition":
            raise AppError("INVALID_INPUT", "Rendering requires a composition package")
        if value.quality == "final":
            project = tx.get(project_path(project_id))
            approval = tx.get(
                project_path(project_id, "approved_compositions", value.composition_artifact_id)
            )
            if (
                project.get("composition_head") != value.composition_artifact_id
                or not approval
                or not approval["approved"]
            ):
                raise AppError(
                    "APPROVAL_REQUIRED", "This exact current composition must be approved in the app", 409
                )


class StudioCommands:
    def generate_video(self, caller, request):
        return self.submit_job(caller, request, "video")

    def generate_music(self, caller, request):
        return self.submit_job(caller, request, "music")

    def prepare_media(self, caller, request):
        return self.submit_job(caller, request, "prepare")

    def extract_frame(self, caller, request):
        return self.submit_job(caller, request, "frame")

    def create_video(self, caller, request):
        return self.submit_job(caller, request, "storyboard")

    def create_hyperframe(self, caller, request):
        return self.submit_job(caller, request, "composition")

    def update_hyperframe(self, caller, request):
        return self.submit_job(caller, request, "composition")

    def render_hyperframe(self, caller, request):
        return self.submit_job(caller, request, "render")

    def edit_hyperframe(self, caller, request):
        return self.submit_job(caller, request, "edit")

    def invalidated_assets(self, caller, project_id, artifact_id):
        self.authorize(caller, project_id)
        self._artifact(project_id, artifact_id)
        from tools.composition.edits import invalidation

        return DataResult(data={"artifact_ids": invalidation(self, project_id, [artifact_id])})

    def inspect_media(self, caller, project_id, artifact_id):
        self.authorize(caller, project_id)
        return DataResult(data=self._artifact(project_id, artifact_id)["media"])

    def get_hyperframe(self, caller, project_id, artifact_id=None):
        project = self.authorize(caller, project_id)
        artifact_id = artifact_id or project.get("composition_head")
        if not artifact_id:
            return DataResult(data={"artifact_id": None, "manifest": None})
        artifact = self._artifact(project_id, artifact_id)
        if artifact["type"] != "composition":
            raise AppError("INVALID_INPUT", "Artifact is not a composition")
        data, _ = self.asset_content(caller, project_id, artifact_id)
        manifest, _ = unpack(data)
        return DataResult(
            data={
                "artifact_id": artifact_id,
                "manifest": manifest,
                "current": project.get("composition_head") == artifact_id,
            }
        )

    def get_storyboard(self, caller, project_id, artifact_id):
        from tools.contracts.studio import Storyboard

        self.authorize(caller, project_id)
        if self._artifact(project_id, artifact_id)["type"] != "storyboard":
            raise AppError("INVALID_INPUT", "Artifact is not a storyboard")
        data, _ = self.asset_content(caller, project_id, artifact_id)
        return DataResult(data=Storyboard.model_validate_json(data).model_dump())

    def studio_state(self, caller, project_id):
        from tools.commands import project_path

        project = self.authorize(caller, project_id)
        jobs = self.repo.recent(project_path(project_id, "jobs"), 60)
        runs = self.repo.recent(project_path(project_id, "runs"), 20)
        approvals = self.repo.recent(project_path(project_id, "approvals"), 20)
        approvals_by_id = {a["id"]: a for a in approvals}
        return DataResult(
            data={
                "project": {
                    k: project.get(k) for k in ("project_id", "name", "brand_version", "composition_head")
                },
                "budget": self.repo.get("budgets/" + project_id),
                "provider_route": self.settings.provider,
                "runs": [
                    self._run_result(
                        r,
                        [j for j in jobs if j["run_id"] == r["run_id"]],
                        approvals_by_id.get(r.get("pending_approval_id")),
                    ).model_dump()
                    for r in runs
                ],
                "jobs": [
                    JobResult(**{k: j[k] for k in JobResult.model_fields if k in j}).model_dump()
                    | {"kind": j.get("kind", "image")}
                    for j in jobs
                ],
                "assets": self.list_assets(caller, project_id, 100).model_dump(),
                "approvals": approvals,
                "brand": self.repo.get(
                    project_path(project_id, "brands", f"brand_{project['brand_version']}")
                ),
                "events": self.repo.recent(project_path(project_id, "events"), 60),
            }
        )

    def decide_approval(self, caller, project_id, approval_id, request):
        from tools.commands import project_path

        if caller.projects is not None or caller.grant_id:
            raise AppError("ACCESS_DENIED", "Approval requires human app authentication", 403)

        def apply(tx):
            self.authorize(caller, project_id, GENERATE, tx)

            def build():
                path = project_path(project_id, "approvals", approval_id)
                approval = tx.get(path)
                if not approval or approval["target_artifact_id"] != request.target_artifact_id:
                    raise AppError("REVISION_CONFLICT", "Approval target mismatch", 409)
                if approval["decision"] != "pending":
                    raise AppError("REVISION_CONFLICT", "Approval already decided", 409)
                run = (
                    tx.get(project_path(project_id, "runs", approval["run_id"]))
                    if approval.get("run_id")
                    else None
                )
                if run and (run["status"] == "cancelled" or run.get("pending_approval_id") != approval_id):
                    raise AppError("REVISION_CONFLICT", "Approval is no longer current", 409)
                if approval["kind"] == "preview":
                    project = tx.get(project_path(project_id))
                    if project.get("composition_head") != request.target_artifact_id:
                        raise AppError("REVISION_CONFLICT", "Preview revision is stale", 409)
                    tx.set(
                        project_path(project_id, "approved_compositions", request.target_artifact_id),
                        {
                            "approved": request.approved,
                            "reviewer_uid": caller.uid,
                            "approval_id": approval_id,
                        },
                    )
                approval.update(
                    decision="approved" if request.approved else "rejected",
                    reviewer_uid=caller.uid,
                    decided_at=self.clock(),
                )
                tx.set(path, approval)
                if run:
                    run["pending_approval_id"] = None
                    run["status"] = "waiting_for_jobs" if request.approved else "failed"
                    run["version"] += 1
                    tx.set(project_path(project_id, "runs", run["run_id"]), run)
                    self.project_run(tx, run)
                return approval

            return self._idempotent(
                tx,
                project_path(project_id),
                "approval.decide",
                request.idempotency_key,
                request.model_dump() | {"approval_id": approval_id},
                build,
                caller.uid,
            )

        return DataResult(data=self.repo.atomic(apply))

    def request_preview_approval(self, caller, project_id, artifact_id, key):
        from tools.commands import identifier, project_path

        def apply(tx):
            self.authorize(caller, project_id, GENERATE, tx)

            def build():
                artifact = self._artifact(project_id, artifact_id, tx)
                if artifact["type"] != "composition":
                    raise AppError("INVALID_INPUT", "Composition required")
                approval_id = identifier("approval")
                approval = {
                    "id": approval_id,
                    "kind": "preview",
                    "run_id": None,
                    "target_artifact_id": artifact_id,
                    "decision": "pending",
                    "created_at": self.clock(),
                    "review_url": f"{self.settings.web_url}/projects/{project_id}",
                }
                tx.set(project_path(project_id, "approvals", approval_id), approval)
                return approval

            return self._idempotent(
                tx,
                project_path(project_id),
                "preview.request",
                key,
                {"artifact_id": artifact_id},
                build,
                caller.uid,
            )

        return DataResult(data=self.repo.atomic(apply))

    def update_member(self, caller, project_id, request):
        from tools.commands import checked_id, project_path

        def apply(tx):
            project = self.authorize(caller, project_id, GENERATE, tx)
            if project["owner_uid"] != caller.uid or caller.projects is not None:
                raise AppError("ACCESS_DENIED", "Only the project owner may manage members", 403)

            def build():
                checked_id(request.uid)
                user = tx.get("users/" + request.uid)
                if not user or not user["access_enabled"]:
                    raise AppError("INVALID_INPUT", "Member must first sign in to VibeShorts")
                if request.uid == project["owner_uid"]:
                    raise AppError("INVALID_INPUT", "Owner cannot be removed")
                if request.role:
                    project["members"][request.uid] = request.role
                else:
                    project["members"].pop(request.uid, None)
                tx.set(project_path(project_id), project)
                return {"uid": request.uid, "role": request.role}

            return self._idempotent(
                tx,
                project_path(project_id),
                "member.update",
                request.idempotency_key,
                request.model_dump(),
                build,
                caller.uid,
            )

        return DataResult(data=self.repo.atomic(apply))

    def brand_assessment(self, caller, project_id, artifact_id):
        self.authorize(caller, project_id)
        artifact = self._artifact(project_id, artifact_id)
        project = self.authorize(caller, project_id)
        from tools.commands import project_path

        brand = self.repo.get(project_path(project_id, "brands", f"brand_{project['brand_version']}"))
        result = {
            "artifact_id": artifact_id,
            "method": "deterministic required-asset and palette checks",
            "checks": [],
        }
        if artifact["type"] == "composition":
            manifest = self.get_hyperframe(caller, project_id, artifact_id).data["manifest"]
            palette = {manifest["timeline"][k].lower() for k in ("background", "foreground", "accent")}
            inputs = set(manifest["input_artifact_ids"])
            if brand:
                for color in brand.get("colors", {}).values():
                    result["checks"].append({"label": color, "passed": color.lower() in palette})
                if brand.get("logo"):
                    result["checks"].append({"label": "Exact brand logo", "passed": brand["logo"] in inputs})
                for role, font in brand.get("fonts", {}).items():
                    result["checks"].append({"label": "Exact " + role + " font", "passed": font in inputs})
        result["passed"] = bool(result["checks"]) and all(c["passed"] for c in result["checks"])
        return DataResult(data=result)
