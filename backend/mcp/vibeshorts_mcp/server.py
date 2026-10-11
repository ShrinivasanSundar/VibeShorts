import asyncio
import json

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent
from pydantic import AnyHttpUrl

from tools.contracts.errors import AppError
from tools.contracts.models import (
    AssetPage,
    Caller,
    DataResult,
    ImageCommand,
    ImageInput,
    JobHandle,
    JobResult,
    RunResult,
)


class BrokerVerifier(TokenVerifier):
    def __init__(self, broker):
        self.broker = broker

    async def verify_token(self, token: str):
        try:
            caller, expiry, client_id = await asyncio.to_thread(self.broker.verify, token)
            return AccessToken(
                token=token,
                client_id=client_id,
                scopes=caller.scopes,
                expires_at=int(expiry),
                resource=self.broker.resource,
                subject=caller.uid,
                claims=caller.model_dump(),
            )
        except AppError:
            return None


def build_server(runtime, stdio_caller=None):
    broker, commands = runtime.oauth, runtime.commands
    kwargs = {}
    if stdio_caller is None:
        kwargs = {
            "token_verifier": BrokerVerifier(broker),
            "auth": AuthSettings(
                issuer_url=AnyHttpUrl(commands.settings.public_url),
                resource_server_url=AnyHttpUrl(broker.resource),
                required_scopes=["vibeshorts:read"],
                validate_token_resource=True,
            ),
        }
    server = MCPServer(
        "VibeShorts",
        version="0.1.0",
        instructions=(
            "Image generation submits a durable job. Poll get_job; "
            "retrieve completed artifacts with get_asset. "
            "An uncertain submission requires operator reconciliation "
            "and must not be automatically retried."
        ),
        **kwargs,
    )

    def caller():
        if stdio_caller is not None:
            return stdio_caller
        token = get_access_token()
        if token is None or not token.claims:
            raise AppError("UNAUTHENTICATED", "MCP authentication required", 401)
        return Caller(**token.claims)

    async def invoke(action, *args, **kwargs):
        try:
            trusted = caller()
            return await asyncio.to_thread(action, trusted, *args, **kwargs)
        except AppError as exc:
            data = exc.payload.model_dump(exclude_none=True)
            return CallToolResult(is_error=True, content=[TextContent(type="text", text=json.dumps(data))])

    @server.tool(structured_output=True)
    async def generate_image(project_id: str, idempotency_key: str, input: ImageInput) -> JobHandle:
        """Submit an image job; this result is not a completed image."""
        return await invoke(
            commands.generate_image,
            ImageCommand(project_id=project_id, idempotency_key=idempotency_key, input=input),
        )

    @server.tool(structured_output=True)
    async def get_job(project_id: str, job_id: str) -> JobResult:
        """Read job state, artifact ids, costs and any actionable error."""
        return await invoke(commands.get_job, project_id, job_id)

    @server.tool(structured_output=True)
    async def get_run(project_id: str, run_id: str) -> RunResult:
        """Read a compact standalone run summary."""
        return await invoke(commands.get_run, project_id, run_id)

    @server.tool(structured_output=True)
    async def cancel_job(project_id: str, job_id: str, idempotency_key: str) -> JobHandle:
        """Cancel new job work without erasing accepted-operation liability."""
        return await invoke(commands.cancel_job, project_id, job_id, idempotency_key)

    @server.tool(structured_output=True)
    async def cancel_run(project_id: str, run_id: str, idempotency_key: str) -> JobHandle:
        """Cancel the run's image operation."""
        return await invoke(commands.cancel_run, project_id, run_id, idempotency_key)

    @server.tool(structured_output=True)
    async def get_asset(project_id: str, artifact_id: str) -> DataResult:
        """Read artifact metadata and authorized download information."""
        return await invoke(commands.get_asset, project_id, artifact_id)

    @server.tool(structured_output=True)
    async def list_assets(
        project_id: str,
        limit: int = 20,
        cursor: str | None = None,
        type: str | None = None,
        status: str | None = None,
    ) -> AssetPage:
        """List up to 100 authorized ready artifacts with an opaque cursor."""
        return await invoke(commands.list_assets, project_id, limit, cursor, type, status)

    @server.tool(structured_output=True)
    async def get_brand_dna(project_id: str, version: int | None = None) -> DataResult:
        """Read one immutable brand revision."""
        return await invoke(commands.get_brand_dna, project_id, version)

    @server.tool(structured_output=True)
    async def get_project_context(project_id: str) -> DataResult:
        """Read a bounded project summary, without events or media bytes."""
        return await invoke(commands.get_project_context, project_id)

    @server.tool(structured_output=True)
    async def get_capabilities(project_id: str) -> DataResult:
        """Read the configured image route, lifecycle status and supported settings."""
        return await invoke(commands.get_capabilities, project_id)

    from tools.contracts.studio import (
        BriefInput,
        Composition,
        FrameInput,
        MusicInput,
        PrepareInput,
        RenderInput,
        StudioCommand,
        VideoInput,
    )

    @server.tool(structured_output=True)
    async def generate_video(project_id: str, idempotency_key: str, input: VideoInput) -> JobHandle:
        """Submit a first-frame video job. Poll the existing operation; never repurchase on uncertainty."""
        return await invoke(
            commands.generate_video,
            StudioCommand(project_id=project_id, idempotency_key=idempotency_key, input=input),
        )

    @server.tool(structured_output=True)
    async def generate_music(project_id: str, idempotency_key: str, input: MusicInput) -> JobHandle:
        """Submit reviewed instrumental music generation."""
        return await invoke(
            commands.generate_music,
            StudioCommand(project_id=project_id, idempotency_key=idempotency_key, input=input),
        )

    @server.tool(structured_output=True)
    async def inspect_media(project_id: str, artifact_id: str) -> DataResult:
        """Read verified decoded media facts."""
        return await invoke(commands.inspect_media, project_id, artifact_id)

    @server.tool(structured_output=True)
    async def extract_frame(project_id: str, idempotency_key: str, input: FrameInput) -> JobHandle:
        """Extract an exact displayed source frame into an immutable continuity anchor."""
        return await invoke(
            commands.extract_frame,
            StudioCommand(project_id=project_id, idempotency_key=idempotency_key, input=input),
        )

    @server.tool(structured_output=True)
    async def prepare_media(project_id: str, idempotency_key: str, input: PrepareInput) -> JobHandle:
        """Submit bounded trim, normalization, scale and audio preparation."""
        return await invoke(
            commands.prepare_media,
            StudioCommand(project_id=project_id, idempotency_key=idempotency_key, input=input),
        )

    @server.tool(structured_output=True)
    async def get_hyperframe(project_id: str, artifact_id: str | None = None) -> DataResult:
        """Read the immutable package manifest and typed timeline."""
        return await invoke(commands.get_hyperframe, project_id, artifact_id)

    @server.tool(structured_output=True)
    async def create_hyperframe(project_id: str, idempotency_key: str, input: Composition) -> JobHandle:
        """Submit a typed, validated package write against the expected head."""
        return await invoke(
            commands.create_hyperframe,
            StudioCommand(project_id=project_id, idempotency_key=idempotency_key, input=input),
        )

    @server.tool(structured_output=True)
    async def update_hyperframe(project_id: str, idempotency_key: str, input: Composition) -> JobHandle:
        """Create an immutable revision; conflicting Studio/director writes return a conflict."""
        return await invoke(
            commands.update_hyperframe,
            StudioCommand(project_id=project_id, idempotency_key=idempotency_key, input=input),
        )

    @server.tool(structured_output=True)
    async def render_hyperframe(project_id: str, idempotency_key: str, input: RenderInput) -> JobHandle:
        """Submit a draft or a final export of an exact human-approved current revision."""
        return await invoke(
            commands.render_hyperframe,
            StudioCommand(project_id=project_id, idempotency_key=idempotency_key, input=input),
        )

    @server.tool(structured_output=True)
    async def create_video(project_id: str, idempotency_key: str, input: BriefInput) -> JobHandle:
        """Submit a Director workflow with human storyboard and preview approval gates."""
        return await invoke(
            commands.create_video,
            StudioCommand(project_id=project_id, idempotency_key=idempotency_key, input=input),
        )

    return server


def http_app(server, settings):
    from urllib.parse import urlparse

    hosts = [urlparse(settings.public_url).netloc]
    if settings.mode == "emulator":
        hosts += ["localhost:*", "127.0.0.1:*"]
    return server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=[settings.public_url, settings.web_url],
        ),
    )


def main():
    from execution.runtime import Runtime
    from tools.contracts.models import SCOPES

    runtime = Runtime.create()
    settings = runtime.commands.settings
    if not settings.stdio_firebase_id_token or not settings.stdio_projects or not settings.stdio_scopes:
        raise SystemExit("Stdio requires VIBESHORTS_STDIO_FIREBASE_ID_TOKEN, STDIO_PROJECTS and STDIO_SCOPES")
    caller = runtime.commands.identity.verify(settings.stdio_firebase_id_token)
    caller.projects = settings.stdio_projects.split(",")
    caller.scopes = settings.stdio_scopes.split(",")
    if not set(caller.scopes) <= SCOPES:
        raise SystemExit("Unknown stdio scope")
    for project_id in caller.projects:
        for scope in caller.scopes:
            runtime.commands.authorize(caller, project_id, scope)
    build_server(runtime, caller).run("stdio")
