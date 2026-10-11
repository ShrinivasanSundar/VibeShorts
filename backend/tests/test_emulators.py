import asyncio
import os
import secrets
import socket
import subprocess
import threading
import time

import httpx
import httpx2
import pytest
from mcp.client.streamable_http import streamable_http_client

from api.main import create_app
from execution.dispatch import EmulatorPump, Reconciler
from execution.paths import BACKEND_ROOT, NODE_MODULES, REPO_ROOT
from execution.runtime import Runtime
from mcp import Client, StdioServerParameters
from tools.commands import project_path
from tools.contracts.models import ImageCommand, ImageInput, ProjectCreate

pytestmark = [
    pytest.mark.emulator,
    pytest.mark.skipif(not os.getenv("FIRESTORE_EMULATOR_HOST"), reason="Emulators required"),
]


def real_user(runtime):
    host = os.environ["FIREBASE_AUTH_EMULATOR_HOST"]
    response = httpx.post(
        f"http://{host}/identitytoolkit.googleapis.com/v1/accounts:signUp?key=demo-key",
        json={
            "email": f"acceptance-{secrets.token_hex(8)}@example.test",
            "password": "testing-password-123",
            "returnSecureToken": True,
        },
    )
    response.raise_for_status()
    token = response.json()["idToken"]
    return token, runtime.commands.identity.verify(token)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_real_firestore_pubsub_storage_oauth_and_restart(mode, monkeypatch):
    from test_oauth import authorization

    from providers.image import FixtureImageProvider

    prompt = "A product launch frame " + secrets.token_hex(8)
    calls = []
    generate = FixtureImageProvider.generate

    def track(self, request, references, snapshot):
        if request.prompt == prompt:
            calls.append(request.prompt)
        return generate(self, request, references, snapshot)

    monkeypatch.setattr(FixtureImageProvider, "generate", track)

    runtime = Runtime.create()
    token, caller = real_user(runtime)
    project = runtime.commands.create_project(
        caller, ProjectCreate(name="Emulator acceptance", idempotency_key="bootstrap")
    ).data["project_id"]
    oauth_token = runtime.oauth.exchange(authorization(runtime, caller, project))["access_token"]
    app = create_app(runtime)
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app), headers={"Authorization": "Bearer " + oauth_token}
        ) as http:
            async with Client(
                streamable_http_client(runtime.oauth.resource, http_client=http), mode=mode
            ) as client:
                result = await client.call_tool(
                    "generate_image",
                    {
                        "project_id": project,
                        "idempotency_key": "mcp-image",
                        "input": {"prompt": prompt},
                    },
                )
                assert not result.is_error, result
                job = result.structured_content
                # Separate clients reload accepted work from Firestore; no in-process job state.
                restarted = Runtime.create()
                pump = EmulatorPump(restarted.commands, restarted.worker)
                pump.bootstrap()
                await asyncio.to_thread(pump.once)
                for _ in range(10):
                    finished = await client.call_tool(
                        "get_job", {"project_id": project, "job_id": job["job_id"]}
                    )
                    if finished.structured_content["status"] == "succeeded":
                        break
                    await asyncio.to_thread(pump.once)
                assert finished.structured_content["status"] == "succeeded", finished
                artifact = finished.structured_content["artifact_ids"][0]
                data, mime = restarted.commands.asset_content(caller, project, artifact)
                assert mime == "image/png" and data.startswith(b"\x89PNG")
                assert restarted.commands.repo.get("budgets/" + project)["reserved_micros"] == 0
                assert len(calls) == 1
                assert not restarted.worker.execute(project, job["job_id"])
                assert len(calls) == 1


async def test_stdio_external_process_with_explicit_credentials():
    runtime = Runtime.create()
    token, caller = real_user(runtime)
    project = runtime.commands.create_project(
        caller, ProjectCreate(name="Stdio acceptance", idempotency_key="bootstrap")
    ).data["project_id"]
    environment = {
        **os.environ,
        "VIBESHORTS_STDIO_FIREBASE_ID_TOKEN": token,
        "VIBESHORTS_STDIO_PROJECTS": project,
        "VIBESHORTS_STDIO_SCOPES": "vibeshorts:read,vibeshorts:generate,vibeshorts:cancel",
    }
    parameters = StdioServerParameters(
        command=str(BACKEND_ROOT / ".venv/bin/vibeshorts-mcp"), env=environment
    )
    async with Client(parameters) as client:
        assert len((await client.list_tools()).tools) == 20
        result = await client.call_tool(
            "generate_image",
            {"project_id": project, "idempotency_key": "stdio-image", "input": {"prompt": "Product reveal"}},
        )
        assert not result.is_error, result
        job = result.structured_content
        await asyncio.to_thread(runtime.worker.execute, project, job["job_id"])
        finished = await client.call_tool("get_job", {"project_id": project, "job_id": job["job_id"]})
        assert finished.structured_content["status"] == "succeeded"
        denied = await client.call_tool("get_project_context", {"project_id": "not-granted"})
        assert denied.is_error


def test_firestore_restart_recovers_uploaded_candidate_without_regeneration():
    runtime = Runtime.create()
    token, caller = real_user(runtime)
    project = runtime.commands.create_project(
        caller, ProjectCreate(name="Crash acceptance", idempotency_key="bootstrap")
    ).data["project_id"]
    handle = runtime.commands.generate_image(
        caller,
        ImageCommand(project_id=project, idempotency_key="crash", input=ImageInput(prompt="Product reveal")),
    )

    class ProcessDied(BaseException):
        pass

    put = runtime.commands.storage.put

    def crash(*args):
        put(*args)
        raise ProcessDied()

    runtime.commands.storage.put = crash
    with pytest.raises(ProcessDied):
        runtime.worker.execute(project, handle.job_id)
    restarted = Runtime.create()
    # Expire the crashed claim without waiting three minutes.
    path = project_path(project, "jobs", handle.job_id)
    restarted.commands.repo.atomic(lambda tx: tx.set(path, {**tx.get(path), "lease_expires_at": 0}))
    Reconciler(restarted.commands).sweep()
    restarted.worker.execute(project, handle.job_id)
    assert restarted.commands.get_job(caller, project, handle.job_id).status == "succeeded"
    assert runtime.commands.provider.calls == 1
    assert restarted.commands.provider.calls == 0


@pytest.mark.parametrize("era", ["modern", "legacy"])
def test_inspector_external_http_image_workflow(era):
    import json

    import uvicorn
    from test_oauth import authorization

    runtime = Runtime.create()
    token, caller = real_user(runtime)
    project = runtime.commands.create_project(
        caller, ProjectCreate(name="Inspector acceptance", idempotency_key="inspector")
    ).data["project_id"]
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    runtime.commands.settings.public_url = f"http://127.0.0.1:{port}"
    from api.oauth import OAuthBroker

    runtime.oauth = OAuthBroker(runtime.commands)
    token = runtime.oauth.exchange(authorization(runtime, caller, project))["access_token"]
    server = uvicorn.Server(uvicorn.Config(create_app(runtime), log_level="error"))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started
        command = [
            str(NODE_MODULES / ".bin/mcp-inspector"),
            "--cli",
            "--server-url",
            runtime.oauth.resource,
            "--header",
            "Authorization: Bearer " + token,
            "--protocol-era",
            era,
            "--format",
            "json",
        ]
        # Keep all Inspector state inside an ignored project cache.
        environment = {
            **os.environ,
            "MCP_CATALOG_PATH": str(REPO_ROOT / ".cache/inspector/catalog.json"),
            "MCP_CLIENT_CONFIG_PATH": str(REPO_ROOT / ".cache/inspector/client.json"),
        }

        def call(method, *args):
            result = subprocess.run(
                command + ["--method", method, *args],
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, result.stderr
            payload = json.loads(result.stdout)
            assert payload.get("success", payload.get("ok", True)), payload
            return payload.get("result", payload)

        listing = call("tools/list")
        assert len(listing["tools"]) == 20
        submitted = call(
            "tools/call",
            "--tool-name",
            "generate_image",
            "--tool-args-json",
            json.dumps(
                {
                    "project_id": project,
                    "idempotency_key": "inspector-image",
                    "input": {"prompt": "Launch frame"},
                }
            ),
        )
        handle = submitted["structuredContent"]
        runtime.worker.execute(project, handle["job_id"])
        finished = call(
            "tools/call",
            "--tool-name",
            "get_job",
            "--tool-args-json",
            json.dumps({"project_id": project, "job_id": handle["job_id"]}),
        )
        assert finished["structuredContent"]["status"] == "succeeded"
        assert runtime.commands.provider.calls == 1
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
