import asyncio
import base64
import json
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import Field
from vibeshorts_mcp.server import build_server, http_app

from execution.dispatch import Dispatcher, PubSubPublisher, Reconciler
from execution.runtime import Runtime
from execution.telemetry import metrics
from tools.contracts.errors import AppError
from tools.contracts.models import (
    BrandUpdate,
    Caller,
    Contract,
    ImageCommand,
    Mutation,
    ProjectCreate,
    UploadComplete,
    UploadCreate,
)


class Consent(Contract):
    request_id: str = Field(max_length=100)
    project_ids: list[str] = Field(max_length=100)
    approved: bool


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = 200_000_000 if scope["path"].endswith("/content") else 128_000
        size = 0

        async def limited_receive():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > limit:
                raise AppError("PAYLOAD_TOO_LARGE", "Request exceeds permitted size", 413)
            return message

        try:
            await self.app(scope, limited_receive, send)
        except AppError as exc:
            await JSONResponse(exc.payload.model_dump(exclude_none=True), status_code=exc.status)(
                scope, receive, send
            )


def create_app(runtime=None):
    runtime = runtime or Runtime.create()
    commands, broker = runtime.commands, runtime.oauth
    settings = commands.settings
    server = build_server(runtime)
    transport = http_app(server, settings)

    @asynccontextmanager
    async def lifespan(app):
        async with server.session_manager.run():
            yield

    app = FastAPI(title="VibeShorts", version="0.1.0", lifespan=lifespan)
    app.state.runtime = runtime
    app.add_middleware(BodyLimit)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_url],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["WWW-Authenticate", "MCP-Session-Id", "MCP-Protocol-Version"],
    )

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        headers = {"Cache-Control": "no-store"}
        if exc.status == 401:
            headers["WWW-Authenticate"] = "Bearer"
        return JSONResponse(
            exc.payload.model_dump(exclude_none=True), status_code=exc.status, headers=headers
        )

    from google.api_core.exceptions import ResourceExhausted

    @app.exception_handler(ResourceExhausted)
    async def quota_error(request, exc):
        return JSONResponse(
            {
                "code": "FIRESTORE_QUOTA_EXHAUSTED",
                "message": (
                    "Firestore quota is exhausted. Check Firebase usage and billing, "
                    "or retry after the quota resets."
                ),
            },
            status_code=429,
            headers={"Cache-Control": "no-store", "Retry-After": "60"},
        )

    def bearer(authorization):
        if not authorization or not authorization.startswith("Bearer "):
            raise AppError("UNAUTHENTICATED", "Bearer credentials required", 401)
        return authorization[7:]

    def firebase_caller(authorization: Annotated[str | None, Header()] = None):
        caller = commands.identity.verify(bearer(authorization))
        commands.provision(caller)
        return caller

    def media_caller(authorization: Annotated[str | None, Header()] = None):
        raw = bearer(authorization)
        try:
            return broker.verify(raw)[0]
        except AppError:
            return firebase_caller(authorization)

    def internal_caller(request: Request, authorization: Annotated[str | None, Header()] = None):
        if settings.local_live:
            raise AppError("ACCESS_DENIED", "Local live jobs use the pull worker", 403)
        if settings.mode == "emulator":
            if request.client and request.client.host in {"127.0.0.1", "::1", "testclient"}:
                return
            raise AppError("ACCESS_DENIED", "Local internal ingress only", 403)
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2 import id_token

        try:
            claims = id_token.verify_oauth2_token(
                bearer(authorization), GoogleRequest(), settings.internal_audience
            )
            if not claims.get("email_verified") or claims.get(
                "email"
            ) not in settings.internal_service_emails.split(","):
                raise ValueError("Service identity not allowed")
        except Exception as exc:
            raise AppError("ACCESS_DENIED", "Authorized workload identity required", 403) from exc

    from pydantic import ValidationError

    @app.exception_handler(ValidationError)
    async def contract_error(request, exc):
        return JSONResponse({"code": "INVALID_INPUT", "message": "Invalid command payload"}, status_code=422)

    from api.studio import install

    install(app, commands, firebase_caller)

    @app.get("/healthz")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/.well-known/oauth-authorization-server")
    def oauth_metadata():
        return broker.metadata()

    @app.get("/.well-known/oauth-protected-resource")
    def protected_metadata():
        return {
            "resource": broker.resource,
            "authorization_servers": [settings.public_url],
            "scopes_supported": sorted(__import__("tools.contracts.models", fromlist=["SCOPES"]).SCOPES),
        }

    @app.get("/oauth/authorize")
    def authorize(
        client_id: str,
        redirect_uri: str,
        resource: str,
        code_challenge: str,
        scope: str = "vibeshorts:read",
        state: str = "",
        code_challenge_method: str = "S256",
        response_type: str = "code",
    ):
        return RedirectResponse(
            broker.begin(
                client_id,
                redirect_uri,
                resource,
                scope,
                state,
                code_challenge,
                code_challenge_method,
                response_type,
            ),
            status_code=302,
        )

    @app.get("/oauth/requests/{request_id}")
    def consent_details(request_id: str, caller: Caller = Depends(firebase_caller)):
        return broker.request_details(caller, request_id)

    @app.post("/oauth/consent")
    def consent(body: Consent, caller: Caller = Depends(firebase_caller)):
        return {"redirect_url": broker.consent(caller, body.request_id, body.project_ids, body.approved)}

    @app.post("/oauth/token")
    async def token(request: Request):
        form = await request.form()
        parameters = dict(form)
        if len(form.multi_items()) != len(parameters) or not all(
            isinstance(v, str) for v in parameters.values()
        ):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        try:
            result = await asyncio.to_thread(broker.exchange, parameters)
            return JSONResponse(result, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
        except AppError as exc:
            return JSONResponse(
                {
                    "error": exc.payload.code if exc.status == 400 else "invalid_grant",
                    "error_description": exc.payload.message,
                },
                status_code=400,
                headers={"Cache-Control": "no-store"},
            )

    @app.post("/oauth/revoke")
    async def revoke(request: Request):
        form = await request.form()
        await asyncio.to_thread(broker.revoke, str(form.get("token", "")), str(form.get("client_id", "")))
        return Response(status_code=200, headers={"Cache-Control": "no-store"})

    @app.get("/v1/projects")
    def projects(caller: Caller = Depends(firebase_caller)):
        return commands.list_projects(caller)

    @app.post("/v1/projects", status_code=201)
    def create_project(body: ProjectCreate, caller: Caller = Depends(firebase_caller)):
        return commands.create_project(caller, body)

    @app.post("/v1/projects/{project_id}/brand")
    def update_brand(project_id: str, body: BrandUpdate, caller: Caller = Depends(firebase_caller)):
        return commands.update_brand(caller, project_id, body)

    @app.get("/v1/projects/{project_id}/brand")
    def brand(project_id: str, version: int | None = None, caller: Caller = Depends(firebase_caller)):
        return commands.get_brand_dna(caller, project_id, version)

    @app.get("/v1/projects/{project_id}/context")
    def context(project_id: str, caller: Caller = Depends(firebase_caller)):
        return commands.get_project_context(caller, project_id)

    @app.get("/v1/projects/{project_id}/capabilities")
    def capabilities(project_id: str, caller: Caller = Depends(firebase_caller)):
        return commands.get_capabilities(caller, project_id)

    @app.post("/v1/projects/{project_id}/images", status_code=202)
    def image(project_id: str, body: ImageCommand, caller: Caller = Depends(firebase_caller)):
        if body.project_id != project_id:
            raise AppError("INVALID_INPUT", "Project identifiers do not match")
        return commands.generate_image(caller, body)

    @app.get("/v1/projects/{project_id}/jobs/{job_id}")
    def job(project_id: str, job_id: str, caller: Caller = Depends(firebase_caller)):
        return commands.get_job(caller, project_id, job_id)

    @app.get("/v1/projects/{project_id}/runs/{run_id}")
    def run(project_id: str, run_id: str, caller: Caller = Depends(firebase_caller)):
        return commands.get_run(caller, project_id, run_id)

    @app.post("/v1/projects/{project_id}/jobs/{job_id}/cancel")
    def cancel_job(project_id: str, job_id: str, body: Mutation, caller: Caller = Depends(firebase_caller)):
        return commands.cancel_job(caller, project_id, job_id, body.idempotency_key)

    @app.post("/v1/projects/{project_id}/runs/{run_id}/cancel")
    def cancel_run(project_id: str, run_id: str, body: Mutation, caller: Caller = Depends(firebase_caller)):
        return commands.cancel_run(caller, project_id, run_id, body.idempotency_key)

    @app.get("/v1/projects/{project_id}/assets")
    def assets(
        project_id: str,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        cursor: str | None = None,
        type: str | None = None,
        status: str | None = None,
        caller: Caller = Depends(firebase_caller),
    ):
        return commands.list_assets(caller, project_id, limit, cursor, type, status)

    @app.get("/v1/projects/{project_id}/assets/{artifact_id}")
    def asset(project_id: str, artifact_id: str, caller: Caller = Depends(firebase_caller)):
        return commands.get_asset(caller, project_id, artifact_id)

    @app.get("/v1/projects/{project_id}/assets/{artifact_id}/content")
    def asset_bytes(project_id: str, artifact_id: str, caller: Caller = Depends(media_caller)):
        data, mime = commands.asset_content(caller, project_id, artifact_id)
        return Response(data, media_type=mime, headers={"Cache-Control": "private, no-store"})

    @app.post("/v1/projects/{project_id}/uploads")
    def upload(project_id: str, body: UploadCreate, caller: Caller = Depends(firebase_caller)):
        return commands.initiate_upload(caller, project_id, body)

    @app.put("/v1/projects/{project_id}/uploads/{upload_id}/content")
    async def upload_bytes(
        project_id: str, upload_id: str, request: Request, caller: Caller = Depends(firebase_caller)
    ):
        if settings.mode != "emulator" and not settings.local_live:
            raise AppError("ACCESS_DENIED", "Use the object-scoped upload URL", 403)
        data = await request.body()
        return await asyncio.to_thread(
            commands.upload_content, caller, project_id, upload_id, data, request.headers.get("content-type")
        )

    @app.post("/v1/projects/{project_id}/uploads/complete")
    def complete(project_id: str, body: UploadComplete, caller: Caller = Depends(firebase_caller)):
        return commands.complete_upload(caller, project_id, body)

    @app.post("/internal/jobs", dependencies=[Depends(internal_caller)])
    def execute(body: dict):
        try:
            message = json.loads(base64.b64decode(body["message"]["data"], validate=True))
            project_id, job_id = message["project_id"], message["job_id"]
        except (KeyError, ValueError, TypeError) as exc:
            raise AppError("INVALID_INPUT", "Malformed queue envelope", 422) from exc
        runtime.worker.execute(project_id, job_id)
        return {"acknowledged": True}

    @app.post("/internal/dispatch", dependencies=[Depends(internal_caller)])
    def dispatch():
        return {"sent": Dispatcher(commands, PubSubPublisher(settings)).dispatch()}

    @app.post("/internal/reconcile", dependencies=[Depends(internal_caller)])
    def reconcile():
        return {
            "recovered": Reconciler(commands).sweep(),
            "sent": Dispatcher(commands, PubSubPublisher(settings)).dispatch(),
        }

    @app.get("/internal/metrics", dependencies=[Depends(internal_caller)])
    def counters():
        return metrics()

    app.mount("/", transport)
    return app
