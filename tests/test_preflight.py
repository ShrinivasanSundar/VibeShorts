import json

from execution.preflight import paid_smoke_preflight


def test_emulator_preflight_is_blocked_without_cloud_access(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(tmp_path))
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("VIBESHORTS_SMOKE_FIREBASE_ID_TOKEN", raising=False)
    result = paid_smoke_preflight()
    assert not result["ready"] and not result["network_checked"]
    assert any("production mode" in blocker for blocker in result["blockers"])
    assert any("ADC" in blocker for blocker in result["blockers"])


def production(monkeypatch, tmp_path):
    for name in (
        "FIREBASE_AUTH_EMULATOR_HOST",
        "FIRESTORE_EMULATOR_HOST",
        "STORAGE_EMULATOR_HOST",
        "PUBSUB_EMULATOR_HOST",
    ):
        monkeypatch.delenv(name, raising=False)
    values = {
        "VIBESHORTS_MODE": "production",
        "VIBESHORTS_PROVIDER": "vertex",
        "GOOGLE_CLOUD_PROJECT": "real-test-project",
        "VIBESHORTS_BUCKET": "private-test-bucket",
        "VIBESHORTS_PUBLIC_URL": "https://api.example.test",
        "VIBESHORTS_WEB_URL": "https://web.example.test",
        "VIBESHORTS_INTERNAL_AUDIENCE": "https://api.example.test",
        "VIBESHORTS_INTERNAL_SERVICE_EMAILS": "worker@example.test",
        "VIBESHORTS_PAID_ALLOWANCE_MICROS": "100000",
        "VIBESHORTS_PROJECT_CAP_MICROS": "100000",
        "VIBESHORTS_RATE_JSON": json.dumps(
            {
                "version": "test",
                "verified_at": "2026-10-03",
                "input_per_million_micros": 300000,
                "output_per_million_micros": 30000000,
            }
        ),
        "CLOUDSDK_CONFIG": str(tmp_path),
        "VIBESHORTS_SMOKE_FIREBASE_ID_TOKEN": "secret-do-not-print",
    }
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    (tmp_path / "application_default_credentials.json").write_text("{}")


def test_preflight_checks_reservation_without_using_credentials(monkeypatch, tmp_path):
    production(monkeypatch, tmp_path)
    result = paid_smoke_preflight()
    assert result["ready"] and not result["network_checked"]
    assert result["reservation_micros"] == 71271
    assert "secret-do-not-print" not in json.dumps(result)
    monkeypatch.setenv("VIBESHORTS_PAID_ALLOWANCE_MICROS", "1")
    result = paid_smoke_preflight()
    assert not result["ready"]
    assert any("reservation" in blocker for blocker in result["blockers"])


def test_preflight_does_not_echo_credentials_on_configuration_error(monkeypatch, tmp_path):
    production(monkeypatch, tmp_path)
    monkeypatch.setenv("VIBESHORTS_PAID_ALLOWANCE_MICROS", "0")
    result = paid_smoke_preflight()
    assert not result["ready"]
    assert "secret-do-not-print" not in json.dumps(result)
