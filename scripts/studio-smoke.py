"""Authenticated MCP + real emulator video workflow; synthetic fixture reviews only."""

import asyncio
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import httpx2
from mcp.client.streamable_http import streamable_http_client

from apps.api.main import create_app
from apps.api.oauth import pkce_challenge
from execution.dispatch import EmulatorPump
from execution.runtime import Runtime
from mcp import Client


async def main():
    runtime = Runtime.create()
    c = runtime.commands
    if c.settings.provider != "fixture" or c.settings.mode != "emulator":
        raise SystemExit("Acceptance requires fixture generation and demo emulators")
    response = httpx.post(
        f"http://{os.environ['FIREBASE_AUTH_EMULATOR_HOST']}/identitytoolkit.googleapis.com/v1/accounts:signUp?key=demo-key",
        json={
            "email": f"studio-{secrets.token_hex(8)}@example.test",
            "password": "fixture-password-123",
            "returnSecureToken": True,
        },
    )
    response.raise_for_status()
    token = response.json()["idToken"]
    app = create_app(runtime)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url=c.settings.public_url,
            headers={"Authorization": "Bearer " + token},
            timeout=120,
        ) as rest:
            response = await rest.post(
                "/v1/projects", json={"name": "Studio acceptance", "idempotency_key": "project"}
            )
            response.raise_for_status()
            project = response.json()["data"]["project_id"]
            response = await rest.get(
                "/oauth/authorize",
                params={
                    "client_id": "vibeshorts-sdk",
                    "redirect_uri": "http://127.0.0.1:8765/callback",
                    "resource": runtime.oauth.resource,
                    "scope": "vibeshorts:read vibeshorts:generate vibeshorts:cancel",
                    "state": "fixture-state",
                    "code_challenge": pkce_challenge("v" * 64),
                    "code_challenge_method": "S256",
                    "response_type": "code",
                },
            )
            request_id = parse_qs(urlparse(response.headers["location"]).query)["request_id"][0]
            response = await rest.post(
                "/oauth/consent", json={"request_id": request_id, "project_ids": [project], "approved": True}
            )
            response.raise_for_status()
            callback = response.json()["redirect_url"]
            code = parse_qs(urlparse(callback).query)["code"][0]
            response = await rest.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": "vibeshorts-sdk",
                    "redirect_uri": "http://127.0.0.1:8765/callback",
                    "resource": runtime.oauth.resource,
                    "code": code,
                    "code_verifier": "v" * 64,
                },
            )
            response.raise_for_status()
            access = response.json()["access_token"]
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app), headers={"Authorization": "Bearer " + access}
            ) as transport:
                async with Client(
                    streamable_http_client(runtime.oauth.resource, http_client=transport)
                ) as mcp:
                    arguments = {
                        "project_id": project,
                        "idempotency_key": "short",
                        "input": {"brief": "A calm cinematic product launch", "duration_seconds": 6},
                    }
                    first = await mcp.call_tool("create_video", arguments)
                    if first.is_error:
                        raise RuntimeError(first.content)
                    handle = first.structured_content
                    replay = await mcp.call_tool("create_video", arguments)
                    assert replay.structured_content["job_id"] == handle["job_id"]
                    approvals = set()
                    for _ in range(100):
                        restarted = Runtime.create()
                        pump = EmulatorPump(restarted.commands, restarted.worker)
                        pump.bootstrap()
                        await asyncio.to_thread(pump.once)
                        run = (
                            await mcp.call_tool(
                                "get_run", {"project_id": project, "run_id": handle["run_id"]}
                            )
                        ).structured_content
                        if run["status"] in {"failed", "cancelled", "needs_reconciliation"}:
                            raise RuntimeError(json.dumps(run))
                        if run.get("approval") and run["approval"]["decision"] == "pending":
                            approval = run["approval"]
                            response = await rest.post(
                                f"/v1/projects/{project}/approvals/{approval['id']}",
                                json={
                                    "target_artifact_id": approval["target_artifact_id"],
                                    "approved": True,
                                    "idempotency_key": "approve:" + approval["id"],
                                },
                            )
                            response.raise_for_status()
                            approvals.add(approval["kind"])
                        if run["status"] == "succeeded":
                            artifact_id = run["workflow"]["export_artifact_id"]
                            asset = (
                                await mcp.call_tool(
                                    "get_asset", {"project_id": project, "artifact_id": artifact_id}
                                )
                            ).structured_content
                            response = await rest.get(asset["data"]["download_url"])
                            response.raise_for_status()
                            content = response.content
                            assert hashlib.sha256(content).hexdigest() == asset["data"]["content_sha256"]
                            path = Path(".cache/acceptance/studio-final.mp4")
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_bytes(content)
                            assert approvals == {"storyboard", "preview"}
                            print(
                                json.dumps(
                                    {
                                        "project_id": project,
                                        "run_id": handle["run_id"],
                                        "artifact_id": artifact_id,
                                        "file": str(path),
                                        "approvals": sorted(approvals),
                                    }
                                )
                            )
                            return
                        await asyncio.sleep(0.2)
                    raise RuntimeError("Fixture workflow exceeded acceptance deadline")


asyncio.run(main())
