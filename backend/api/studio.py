import base64

from fastapi import Depends, Query

from tools.composition.package import unpack
from tools.contracts.models import Caller, DataResult, Mutation
from tools.contracts.studio import (
    ApprovalDecision,
    BriefInput,
    Composition,
    ConversationAction,
    ConversationCreate,
    ConversationMessage,
    EditInput,
    FrameInput,
    MemberUpdate,
    MusicInput,
    PrepareInput,
    RenderInput,
    StudioCommand,
    VideoInput,
)


def install(app, commands, caller_dependency):
    def submit(caller, project, body, kind):
        if project != body.project_id:
            from tools.contracts.errors import AppError

            raise AppError("INVALID_INPUT", "Project ids do not match")
        return commands.submit_job(caller, body, kind)

    @app.get("/v1/projects/{project_id}/studio")
    def studio(
        project_id: str, conversation_id: str | None = None, caller: Caller = Depends(caller_dependency)
    ):
        return commands.studio_state(caller, project_id, conversation_id)

    @app.get("/v1/projects/{project_id}/conversations")
    def conversations(
        project_id: str,
        limit: int = Query(30, ge=1, le=100),
        cursor: str | None = None,
        caller: Caller = Depends(caller_dependency),
    ):
        return commands.list_conversations(caller, project_id, limit, cursor)

    @app.post("/v1/projects/{project_id}/conversations", status_code=201)
    def create_conversation(
        project_id: str, body: ConversationCreate, caller: Caller = Depends(caller_dependency)
    ):
        return commands.create_conversation(caller, project_id, body)

    @app.delete("/v1/projects/{project_id}/conversations/{conversation_id}")
    def delete_conversation(
        project_id: str, conversation_id: str, caller: Caller = Depends(caller_dependency)
    ):
        return commands.delete_conversation(caller, project_id, conversation_id)

    @app.get("/v1/projects/{project_id}/conversations/{conversation_id}")
    def conversation(
        project_id: str,
        conversation_id: str,
        cursor: str | None = None,
        limit: int = Query(50, ge=1, le=100),
        tail: bool = False,
        since: int | None = Query(None, ge=0),
        caller: Caller = Depends(caller_dependency),
    ):
        return commands.conversation_state(caller, project_id, conversation_id, cursor, limit, tail, since)

    @app.post("/v1/projects/{project_id}/conversations/{conversation_id}/messages", status_code=202)
    def message(
        project_id: str,
        conversation_id: str,
        body: ConversationMessage,
        caller: Caller = Depends(caller_dependency),
    ):
        return commands.send_message(caller, project_id, conversation_id, body)

    @app.post("/v1/projects/{project_id}/conversations/{conversation_id}/actions")
    def conversation_action(
        project_id: str,
        conversation_id: str,
        body: ConversationAction,
        caller: Caller = Depends(caller_dependency),
    ):
        return commands.conversation_action(caller, project_id, conversation_id, body)

    @app.post("/v1/projects/{project_id}/videos", status_code=202)
    def video(project_id: str, body: StudioCommand, caller: Caller = Depends(caller_dependency)):
        body.input = VideoInput.model_validate(body.input.model_dump())
        return submit(caller, project_id, body, "video")

    @app.post("/v1/projects/{project_id}/music", status_code=202)
    def music(project_id: str, body: StudioCommand, caller: Caller = Depends(caller_dependency)):
        body.input = MusicInput.model_validate(body.input.model_dump())
        return submit(caller, project_id, body, "music")

    @app.post("/v1/projects/{project_id}/shorts", status_code=202)
    def short(project_id: str, body: StudioCommand, caller: Caller = Depends(caller_dependency)):
        body.input = BriefInput.model_validate(body.input.model_dump())
        return submit(caller, project_id, body, "storyboard")

    @app.post("/v1/projects/{project_id}/prepare", status_code=202)
    def prepare(project_id: str, body: StudioCommand, caller: Caller = Depends(caller_dependency)):
        body.input = PrepareInput.model_validate(body.input.model_dump())
        return submit(caller, project_id, body, "prepare")

    @app.post("/v1/projects/{project_id}/frames", status_code=202)
    def frame(project_id: str, body: StudioCommand, caller: Caller = Depends(caller_dependency)):
        body.input = FrameInput.model_validate(body.input.model_dump())
        return submit(caller, project_id, body, "frame")

    @app.post("/v1/projects/{project_id}/compositions", status_code=202)
    def composition(project_id: str, body: StudioCommand, caller: Caller = Depends(caller_dependency)):
        body.input = Composition.model_validate(body.input.model_dump())
        return submit(caller, project_id, body, "composition")

    @app.get("/v1/projects/{project_id}/compositions")
    def current(
        project_id: str,
        artifact_id: str | None = None,
        conversation_id: str | None = None,
        caller: Caller = Depends(caller_dependency),
    ):
        return commands.get_hyperframe(caller, project_id, artifact_id, conversation_id)

    @app.get("/v1/projects/{project_id}/storyboards/{artifact_id}")
    def storyboard(project_id: str, artifact_id: str, caller: Caller = Depends(caller_dependency)):
        return commands.get_storyboard(caller, project_id, artifact_id)

    @app.post("/v1/projects/{project_id}/renders", status_code=202)
    def render(project_id: str, body: StudioCommand, caller: Caller = Depends(caller_dependency)):
        body.input = RenderInput.model_validate(body.input.model_dump())
        return submit(caller, project_id, body, "render")

    @app.post("/v1/projects/{project_id}/approvals/{approval_id}")
    def approve(
        project_id: str, approval_id: str, body: ApprovalDecision, caller: Caller = Depends(caller_dependency)
    ):
        return commands.decide_approval(caller, project_id, approval_id, body)

    @app.post("/v1/projects/{project_id}/compositions/{artifact_id}/review")
    def review(
        project_id: str,
        artifact_id: str,
        body: Mutation,
        conversation_id: str | None = None,
        caller: Caller = Depends(caller_dependency),
    ):
        return commands.request_preview_approval(
            caller, project_id, artifact_id, body.idempotency_key, conversation_id
        )

    @app.get("/v1/projects/{project_id}/compositions/{artifact_id}/preview")
    def preview(project_id: str, artifact_id: str, caller: Caller = Depends(caller_dependency)):
        commands.get_hyperframe(caller, project_id, artifact_id)
        data, _ = commands.asset_content(caller, project_id, artifact_id)
        manifest, files = unpack(data)
        document = files["index.html"].decode()
        document = document.replace(
            '<script src="assets/gsap.min.js"></script>',
            "<script>" + files["assets/gsap.min.js"].decode() + "</script>",
        )
        document = document.replace(
            '<script src="assets/runtime.iife.js"></script>',
            "<script>" + files["assets/runtime.iife.js"].decode() + "</script>",
        )
        policy = (
            "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'"
        )
        import html

        document = document.replace(
            '<meta charset="utf-8">',
            '<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="'
            + html.escape(policy, quote=True)
            + '">',
        )
        for path, content in files.items():
            if path.startswith("assets/") and path not in {"assets/gsap.min.js", "assets/runtime.iife.js"}:
                mime = {
                    ".mp4": "video/mp4",
                    ".wav": "audio/wav",
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".mp3": "audio/mpeg",
                    ".woff2": "font/woff2",
                    ".ttf": "font/ttf",
                }
                suffix = "." + path.rsplit(".", 1)[-1]
                document = document.replace(
                    '"' + path + '"',
                    '"data:' + mime[suffix] + ";base64," + base64.b64encode(content).decode() + '"',
                )
        return DataResult(data={"html": document, "profile": manifest["output_profile"]})

    @app.post("/v1/projects/{project_id}/edits", status_code=202)
    def edit(project_id: str, body: StudioCommand, caller: Caller = Depends(caller_dependency)):
        body.input = EditInput.model_validate(body.input.model_dump())
        return submit(caller, project_id, body, "edit")

    @app.get("/v1/projects/{project_id}/assets/{artifact_id}/dependencies")
    def dependencies(project_id: str, artifact_id: str, caller: Caller = Depends(caller_dependency)):
        return commands.invalidated_assets(caller, project_id, artifact_id)

    @app.get("/v1/projects/{project_id}/assets/{artifact_id}/inspect")
    def inspect(project_id: str, artifact_id: str, caller: Caller = Depends(caller_dependency)):
        return commands.inspect_media(caller, project_id, artifact_id)

    @app.get("/v1/projects/{project_id}/assets/{artifact_id}/brand-check")
    def assess(project_id: str, artifact_id: str, caller: Caller = Depends(caller_dependency)):
        return commands.brand_assessment(caller, project_id, artifact_id)

    @app.post("/v1/projects/{project_id}/members")
    def members(project_id: str, body: MemberUpdate, caller: Caller = Depends(caller_dependency)):
        return commands.update_member(caller, project_id, body)

    @app.post("/v1/projects/{project_id}/batch", status_code=202)
    def batch(project_id: str, body: dict, caller: Caller = Depends(caller_dependency)):
        from tools.contracts.errors import AppError

        entries = body.get("briefs", [])
        key = body.get("idempotency_key")
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(entries, list)
            or not 1 <= len(entries) <= 10
        ):
            raise AppError("INVALID_INPUT", "Batch requires an idempotency key and 1–10 typed briefs")
        return DataResult(
            data={
                "jobs": [
                    commands.create_video(
                        caller,
                        StudioCommand(
                            project_id=project_id,
                            idempotency_key=key + ":" + str(i),
                            input=BriefInput.model_validate(item),
                        ),
                    ).model_dump()
                    for i, item in enumerate(entries)
                ]
            }
        )
