import json

from execution.integrations import check_integrations


def env_files(tmp_path, backend, frontend):
    paths = tmp_path / "backend.env", tmp_path / "frontend.env"
    for path, values in zip(paths, (backend, frontend), strict=True):
        path.write_text("".join(f"{key}='{value}'\n" for key, value in values.items()))
    return paths


def fixture_values():
    return (
        {
            "VIBESHORTS_MODE": "emulator",
            "VIBESHORTS_PROVIDER": "fixture",
            "GOOGLE_CLOUD_PROJECT": "demo-vibeshorts",
            "VIBESHORTS_PUBLIC_URL": "http://127.0.0.1:8000",
            "FIREBASE_AUTH_EMULATOR_HOST": "127.0.0.1:19099",
            "FIRESTORE_EMULATOR_HOST": "127.0.0.1:18080",
            "STORAGE_EMULATOR_HOST": "http://127.0.0.1:19199",
            "PUBSUB_EMULATOR_HOST": "127.0.0.1:18085",
        },
        {
            "NEXT_PUBLIC_MODE": "emulator",
            "NEXT_PUBLIC_FIREBASE_PROJECT_ID": "demo-vibeshorts",
            "NEXT_PUBLIC_API_URL": "http://127.0.0.1:8000/",
            "NEXT_PUBLIC_FIREBASE_API_KEY": "demo-key",
            "NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN": "demo-vibeshorts.firebaseapp.com",
            "NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_URL": "http://127.0.0.1:19099",
            "NEXT_PUBLIC_FIRESTORE_EMULATOR_HOST": "127.0.0.1:18080",
        },
    )


def test_matching_fixture_config_is_ready_without_cloud_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "different-exported-project")
    result = check_integrations(*env_files(tmp_path, *fixture_values()))
    assert result == {"ready": True, "blockers": [], "network_checked": False}


def test_checker_reports_cross_app_and_emulator_mismatches(tmp_path):
    backend, frontend = fixture_values()
    backend["GOOGLE_CLOUD_PROJECT"] = "real-project"
    frontend.update(
        NEXT_PUBLIC_API_URL="http://127.0.0.1:9000",
        NEXT_PUBLIC_FIRESTORE_EMULATOR_HOST="127.0.0.1:8080",
        NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_URL="http://127.0.0.1:9099",
    )
    result = check_integrations(*env_files(tmp_path, backend, frontend))
    assert not result["ready"]
    assert len(result["blockers"]) == 5
    assert any("Firebase project" in value for value in result["blockers"])
    assert any("Auth emulator" in value for value in result["blockers"])
    assert any("Firestore emulator" in value for value in result["blockers"])


def test_production_placeholders_and_missing_credentials_do_not_leak_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(tmp_path))
    backend = {
        "VIBESHORTS_MODE": "production",
        "VIBESHORTS_PROVIDER": "vertex",
        "GOOGLE_CLOUD_PROJECT": "real-project",
        "VIBESHORTS_PUBLIC_URL": "https://api.example.test",
        "VIBESHORTS_WEB_URL": "https://web.example.test",
        "VIBESHORTS_INTERNAL_AUDIENCE": "https://api.example.test",
        "VIBESHORTS_INTERNAL_SERVICE_EMAILS": "YOUR_DISPATCHER_EMAIL",
        "VIBESHORTS_VERTEX_PROJECT": "your-vertex-project",
        "VIBESHORTS_VERTEX_CREDENTIALS": str(tmp_path / "private-secret-credentials.json"),
        "VIBESHORTS_PAID_ALLOWANCE_MICROS": 100000,
        "VIBESHORTS_RATE_JSON": json.dumps(
            {
                "version": "test",
                "verified_at": "2026-10-10",
                "input_per_million_micros": 300000,
                "output_per_million_micros": 30000000,
            }
        ),
        "VIBESHORTS_RENDER_RUNNER": "cloud_run",
        "VIBESHORTS_RENDER_CLOUD_JOB": "projects/YOUR_PROJECT/locations/YOUR_REGION/jobs/render",
        "VIBESHORTS_SMOKE_FIREBASE_ID_TOKEN": "private-secret-token",
    }
    frontend = {
        "NEXT_PUBLIC_MODE": "production",
        "NEXT_PUBLIC_API_URL": "https://api.example.test",
        "NEXT_PUBLIC_FIREBASE_PROJECT_ID": "real-project",
        "NEXT_PUBLIC_FIREBASE_API_KEY": "public-web-key",
        "NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN": "real-project.firebaseapp.com",
    }
    result = check_integrations(*env_files(tmp_path, backend, frontend))
    assert not result["ready"]
    assert "Replace the placeholder in VIBESHORTS_VERTEX_PROJECT" in result["blockers"]
    assert "VIBESHORTS_VERTEX_CREDENTIALS must point to an existing credential file" in result["blockers"]
    assert "private-secret" not in json.dumps(result)
