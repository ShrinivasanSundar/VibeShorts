import json
from urllib.parse import parse_qs, urlparse

import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient
from mcp.client.streamable_http import streamable_http_client
from vibeshorts_mcp.server import build_server

from api.main import create_app
from api.oauth import pkce_challenge
from mcp import Client


@pytest.mark.parametrize("mode,version", [("auto", "2026-07-28"), ("legacy", "2025-11-25")])
async def test_inprocess_discovery_and_structured_output(runtime, alice, project, mode, version):
    async with Client(build_server(runtime, alice), mode=mode) as client:
        assert client.protocol_version == version
        tools = (await client.list_tools()).tools
        assert len(tools) == 20
        assert all(tool.output_schema for tool in tools)
        result = await client.call_tool(
            "generate_image",
            {"project_id": project, "idempotency_key": "client", "input": {"prompt": "Product reveal"}},
        )
        assert not result.is_error
        assert result.structured_content["status"] == "queued"
        assert json.loads(result.content[0].text) == result.structured_content
        denied = await client.call_tool("get_project_context", {"project_id": "other-project"})
        assert denied.is_error
        assert json.loads(denied.content[0].text)["code"] == "ACCESS_DENIED"
        invalid = await client.call_tool(
            "generate_image",
            {
                "project_id": project,
                "idempotency_key": "invalid",
                "input": {"prompt": "x", "aspect_ratio": "1:1"},
            },
        )
        assert invalid.is_error


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_remote_oauth_rest_native_parity_and_asset_delivery(runtime, project, mode):
    app = create_app(runtime)
    headers = {"Authorization": "Bearer alice"}
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8000"
        ) as rest:
            verifier = "v" * 64
            params = {
                "client_id": "vibeshorts-sdk",
                "redirect_uri": "http://127.0.0.1:8765/callback",
                "resource": runtime.oauth.resource,
                "scope": "vibeshorts:read vibeshorts:generate vibeshorts:cancel",
                "state": "expected",
                "code_challenge": pkce_challenge(verifier),
                "code_challenge_method": "S256",
            }
            authorize = await rest.get("/oauth/authorize", params=params)
            assert authorize.status_code == 302
            request_id = parse_qs(urlparse(authorize.headers["location"]).query)["request_id"][0]
            details = await rest.get("/oauth/requests/" + request_id, headers=headers)
            assert details.status_code == 200
            assert details.json()["projects"][0]["project_id"] == project
            consent = await rest.post(
                "/oauth/consent",
                headers=headers,
                json={"request_id": request_id, "project_ids": [project], "approved": True},
            )
            code = parse_qs(urlparse(consent.json()["redirect_url"]).query)["code"][0]
            response = await rest.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": params["client_id"],
                    "redirect_uri": params["redirect_uri"],
                    "resource": params["resource"],
                    "code": code,
                    "code_verifier": verifier,
                },
            )
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "no-store"
            token = response.json()["access_token"]
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app), headers={"Authorization": "Bearer " + token}
            ) as http:
                async with Client(
                    streamable_http_client(runtime.oauth.resource, http_client=http), mode=mode
                ) as client:
                    command = {
                        "project_id": project,
                        "idempotency_key": "remote-" + mode,
                        "input": {"prompt": "Product reveal"},
                    }
                    submitted = await client.call_tool("generate_image", command)
                    assert not submitted.is_error, submitted
                    handle = submitted.structured_content
                    replay = await rest.post(f"/v1/projects/{project}/images", headers=headers, json=command)
                    assert replay.json()["job_id"] == handle["job_id"]
                    runtime.worker.execute(project, handle["job_id"])
                    completed = await client.call_tool(
                        "get_job", {"project_id": project, "job_id": handle["job_id"]}
                    )
                    assert completed.structured_content["status"] == "succeeded"
                    asset_id = completed.structured_content["artifact_ids"][0]
                    asset = await client.call_tool(
                        "get_asset", {"project_id": project, "artifact_id": asset_id}
                    )
                    url = asset.structured_content["data"]["download_url"]
                    private = await rest.get(url)
                    assert private.status_code == 401
                    download = await rest.get(url, headers={"Authorization": "Bearer " + token})
                    assert download.status_code == 200 and download.headers["content-type"] == "image/png"
                    assert runtime.commands.provider.calls == 1


def test_rest_and_mcp_authentication_boundaries(runtime, project):
    with TestClient(create_app(runtime)) as client:
        for header in ({}, {"Authorization": "Bearer invalid"}):
            response = client.post(
                "/v1/projects", headers=header, json={"name": "Unauthorized", "idempotency_key": "no"}
            )
            assert response.status_code == 401
        for header in ({}, {"Authorization": "Bearer alice"}):
            response = client.post(
                "/mcp",
                headers={**header, "Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "server/discover"},
            )
            assert response.status_code == 401
            assert "resource_metadata" in response.headers["www-authenticate"]
        denied = client.get(f"/v1/projects/{project}/context", headers={"Authorization": "Bearer bob"})
        assert denied.status_code == 403
        forged = client.post(
            f"/v1/projects/{project}/images",
            headers={"Authorization": "Bearer alice"},
            json={"project_id": project, "idempotency_key": "forged", "input": {"prompt": "x"}, "uid": "bob"},
        )
        assert forged.status_code == 422
        assert not runtime.commands.repo.list(f"projects/{project}/jobs")
