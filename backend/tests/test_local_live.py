import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.main import create_app
from execution import cli
from execution.config import Settings
from execution.integrations import check_integrations


def live_settings(**overrides):
    values = {
        "mode": "production",
        "provider": "vertex",
        "GOOGLE_CLOUD_PROJECT": "firebase-project",
        "vertex_project": "vertex-project",
        "bucket": "private-bucket",
        "paid_allowance_micros": 100000,
        "rate_json": json.dumps(
            {
                "version": "test",
                "verified_at": "2026-10-10",
                "input_per_million_micros": 300000,
                "output_per_million_micros": 30000000,
            }
        ),
    }
    return Settings(**(values | overrides))


def test_local_live_keeps_real_provider_and_requires_explicit_opt_in():
    with pytest.raises(ValidationError, match="HTTPS"):
        live_settings()
    settings = live_settings(local_live=True)
    assert settings.provider == "vertex" and settings.mode == "production"
    assert settings.vertex_cloud_project == "vertex-project"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://example.com",
        "http://0.0.0.0:8000",
        "http://127.0.0.1.example.com:8000",
        "http://user:password@127.0.0.1:8000",
        "http://127.0.0.1:8000/api",
    ],
)
def test_local_live_rejects_non_loopback_origins(url):
    with pytest.raises(ValidationError, match="loopback origins"):
        live_settings(local_live=True, public_url=url)


def test_local_live_rejects_emulator_connections(monkeypatch):
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:18080")
    with pytest.raises(ValidationError, match="Emulator variables"):
        live_settings(local_live=True)


def test_deployed_production_still_requires_internal_identity():
    with pytest.raises(ValidationError, match="internal service identity"):
        live_settings(public_url="https://api.example.test", web_url="https://web.example.test")


def test_local_live_does_not_expose_internal_worker_routes(runtime):
    runtime.commands.settings.local_live = True
    runtime.commands.settings.mode = "production"
    with TestClient(create_app(runtime)) as client:
        assert client.get("/v1/projects").status_code == 401
        assert client.post("/internal/jobs", json={}).status_code == 403
        assert client.post("/internal/reconcile").status_code == 403


def test_local_live_asset_transfer_requires_owner_auth_without_signing(runtime, project, png, monkeypatch):
    runtime.commands.settings.local_live = True
    runtime.commands.settings.mode = "production"

    def reject_signing(*args, **kwargs):
        pytest.fail("Local live asset transfers must not require signing credentials")

    monkeypatch.setattr(runtime.commands.storage, "signed_url", reject_signing, raising=False)
    owner = {"Authorization": "Bearer alice"}
    other = {"Authorization": "Bearer bob"}
    with TestClient(create_app(runtime)) as client:
        upload = client.post(
            f"/v1/projects/{project}/uploads",
            headers=owner,
            json={
                "idempotency_key": "upload",
                "title": "Reference",
                "mime_type": "image/png",
                "size_bytes": len(png),
            },
        ).json()["data"]
        assert upload["requires_authorization"]
        path = f"/v1/projects/{project}/uploads/{upload['upload_id']}/content"
        assert client.put(path, content=png, headers={"Content-Type": "image/png"}).status_code == 401
        assert client.put(path, content=png, headers=other | {"Content-Type": "image/png"}).status_code == 403
        assert client.put(path, content=png, headers=owner | {"Content-Type": "image/png"}).status_code == 200
        asset = client.post(
            f"/v1/projects/{project}/uploads/complete",
            headers=owner,
            json={"upload_id": upload["upload_id"], "idempotency_key": "complete"},
        ).json()["data"]
        details = client.get(f"/v1/projects/{project}/assets/{asset['id']}", headers=owner).json()["data"]
        assert details["requires_authorization"]
        path = f"/v1/projects/{project}/assets/{asset['id']}/content"
        assert client.get(path).status_code == 401
        assert client.get(path, headers=other).status_code == 403
        response = client.get(path, headers=owner)
        assert response.status_code == 200 and response.content == png


def test_deployed_production_rejects_api_upload_bytes(runtime, project):
    runtime.commands.settings.mode = "production"
    with TestClient(create_app(runtime)) as client:
        assert (
            client.put(
                f"/v1/projects/{project}/uploads/example/content",
                headers={"Authorization": "Bearer alice"},
                content=b"example",
            ).status_code
            == 403
        )


def test_local_live_image_check_does_not_require_media_rates(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(tmp_path))
    (tmp_path / "application_default_credentials.json").write_text("{}")
    settings = live_settings(local_live=True)
    backend = tmp_path / "backend.env"
    backend.write_text(
        "VIBESHORTS_MODE=production\nVIBESHORTS_PROVIDER=vertex\nVIBESHORTS_LOCAL_LIVE=1\n"
        "GOOGLE_CLOUD_PROJECT=firebase-project\nVIBESHORTS_VERTEX_PROJECT=vertex-project\n"
        "VIBESHORTS_BUCKET=private-bucket\nVIBESHORTS_PAID_ALLOWANCE_MICROS=100000\n"
        "VIBESHORTS_PUBLIC_URL=http://127.0.0.1:8000\n"
        "VIBESHORTS_WEB_URL=http://127.0.0.1:3000\n"
        f"VIBESHORTS_RATE_JSON='{settings.rate_json}'\n"
    )
    frontend = tmp_path / "frontend.env"
    frontend.write_text(
        "NEXT_PUBLIC_MODE=production\nNEXT_PUBLIC_API_URL=http://127.0.0.1:8000\n"
        "NEXT_PUBLIC_FIREBASE_PROJECT_ID=firebase-project\n"
        "NEXT_PUBLIC_FIREBASE_API_KEY=public-key\n"
        "NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=firebase-project.firebaseapp.com\n"
    )
    assert check_integrations(backend, frontend, include_media=False)["ready"]
    assert not check_integrations(backend, frontend)["ready"]


def test_local_live_api_binds_only_to_loopback(monkeypatch):
    import uvicorn

    seen = {}
    monkeypatch.setattr("sys.argv", ["vibeshorts", "serve"])
    monkeypatch.setattr(cli, "Settings", lambda: SimpleNamespace(local_live=True))
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: seen.update(kwargs))
    cli.main()
    assert seen["host"] == "127.0.0.1"


@pytest.mark.parametrize("local_live", [True, False])
def test_production_pull_worker_requires_local_live_opt_in(monkeypatch, local_live):
    seen = []
    settings = SimpleNamespace(mode="production", local_live=local_live)
    runtime = SimpleNamespace(commands=SimpleNamespace(settings=settings), worker=object())
    monkeypatch.setattr("sys.argv", ["vibeshorts", "worker"])
    monkeypatch.setattr(cli.Runtime, "create", lambda: runtime)
    monkeypatch.setattr(cli, "EmulatorPump", lambda *args: SimpleNamespace(run=lambda: seen.append(True)))
    if local_live:
        cli.main()
        assert seen == [True]
    else:
        with pytest.raises(SystemExit):
            cli.main()
        assert not seen
