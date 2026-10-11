"""Offline checks for the frontend/backend integration configuration."""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values
from pydantic import ValidationError

from execution.config import Settings
from execution.paths import BACKEND_ROOT, REPO_ROOT


def placeholder(value):
    value = str(value or "").lower()
    return any(marker in value for marker in ("your_", "your-", "/absolute/path/"))


def check_integrations(backend_env=None, frontend_env=None, *, include_media=True):
    backend_env = Path(backend_env or BACKEND_ROOT / ".env")
    frontend_env = Path(frontend_env or REPO_ROOT / "frontend/.env.local")
    blockers = []
    for path in (backend_env, frontend_env):
        if not path.is_file():
            blockers.append(f"Environment file is missing: {path}")
    if blockers:
        return {"ready": False, "blockers": blockers, "network_checked": False}
    backend, frontend = dotenv_values(backend_env), dotenv_values(frontend_env)
    # Supply every field so exported variables cannot hide errors in these files.
    fields = {
        field.validation_alias or name: backend.get(
            field.validation_alias or f"VIBESHORTS_{name.upper()}", field.get_default()
        )
        for name, field in Settings.model_fields.items()
    }
    try:
        Settings(**fields)
    except ValidationError as exc:
        blockers.extend(f"Backend configuration: {error['msg']}" for error in exc.errors())
    mode = backend.get("VIBESHORTS_MODE", "emulator")
    local_live = str(backend.get("VIBESHORTS_LOCAL_LIVE") or "").lower() in {"1", "true", "yes", "on"}
    if frontend.get("NEXT_PUBLIC_MODE", "emulator") != mode:
        blockers.append("Frontend and backend modes must match")
    if frontend.get("NEXT_PUBLIC_FIREBASE_PROJECT_ID") != backend.get("GOOGLE_CLOUD_PROJECT"):
        blockers.append("Frontend Firebase project must match backend GOOGLE_CLOUD_PROJECT")
    api_url = backend.get("VIBESHORTS_PUBLIC_URL") or "http://127.0.0.1:8000"
    if (frontend.get("NEXT_PUBLIC_API_URL") or "").rstrip("/") != api_url.rstrip("/"):
        blockers.append("NEXT_PUBLIC_API_URL must match VIBESHORTS_PUBLIC_URL")
    for key in ("NEXT_PUBLIC_FIREBASE_API_KEY", "NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN"):
        if not frontend.get(key) or placeholder(frontend[key]):
            blockers.append(f"Configure {key}")
    if mode == "emulator":
        if not (backend.get("GOOGLE_CLOUD_PROJECT") or "").startswith("demo-"):
            blockers.append("Fixture emulators require a demo- project")
        for key in (
            "FIREBASE_AUTH_EMULATOR_HOST",
            "FIRESTORE_EMULATOR_HOST",
            "STORAGE_EMULATOR_HOST",
            "PUBSUB_EMULATOR_HOST",
        ):
            if not backend.get(key):
                blockers.append(f"Configure {key}")
        auth_host = urlparse(frontend.get("NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_URL") or "").netloc
        if auth_host != backend.get("FIREBASE_AUTH_EMULATOR_HOST"):
            blockers.append("Frontend and backend Auth emulator addresses must match")
        firestore_host = frontend.get("NEXT_PUBLIC_FIRESTORE_EMULATOR_HOST", "127.0.0.1:18080")
        if firestore_host != backend.get("FIRESTORE_EMULATOR_HOST"):
            blockers.append("Frontend and backend Firestore emulator addresses must match")
    else:
        for key in (
            "GOOGLE_CLOUD_PROJECT",
            "VIBESHORTS_VERTEX_PROJECT",
            "VIBESHORTS_BUCKET",
            "VIBESHORTS_PUBLIC_URL",
            "VIBESHORTS_WEB_URL",
        ):
            if placeholder(backend.get(key)):
                blockers.append(f"Replace the placeholder in {key}")
        if not local_live:
            for key in ("VIBESHORTS_INTERNAL_AUDIENCE", "VIBESHORTS_INTERNAL_SERVICE_EMAILS"):
                if placeholder(backend.get(key)):
                    blockers.append(f"Replace the placeholder in {key}")
        for key in ("GOOGLE_APPLICATION_CREDENTIALS", "VIBESHORTS_VERTEX_CREDENTIALS"):
            if backend.get(key) and not Path(backend[key]).expanduser().is_file():
                blockers.append(f"{key} must point to an existing credential file")
        if not backend.get("GOOGLE_APPLICATION_CREDENTIALS"):
            adc = Path(os.getenv("CLOUDSDK_CONFIG", str(Path.home() / ".config/gcloud")))
            if not (adc / "application_default_credentials.json").is_file():
                blockers.append("Configure application ADC credentials")
        cloud_render = backend.get("VIBESHORTS_RENDER_RUNNER") == "cloud_run"
        if include_media and cloud_render:
            if not backend.get("VIBESHORTS_RENDER_CLOUD_JOB") or placeholder(
                backend.get("VIBESHORTS_RENDER_CLOUD_JOB")
            ):
                blockers.append("Configure VIBESHORTS_RENDER_CLOUD_JOB")
        if frontend.get("NEXT_PUBLIC_FIREBASE_API_KEY") == "demo-key":
            blockers.append("Production sign-in requires the real Firebase web API key")
        if frontend.get("NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_URL"):
            blockers.append("Remove the Auth emulator URL from the production frontend")
        if frontend.get("NEXT_PUBLIC_FIRESTORE_EMULATOR_HOST"):
            blockers.append("Remove the Firestore emulator address from the production frontend")
        try:
            rates = json.loads(backend.get("VIBESHORTS_RATE_JSON") or "{}")
        except ValueError:
            rates = {}
        if not isinstance(rates, dict):
            rates = {}
        rate_keys = [
            "video_per_second_micros",
            "music_per_call_micros",
            "director_reservation_micros",
        ]
        if cloud_render:
            rate_keys.append("render_per_call_micros")
        for key in rate_keys if include_media else []:
            if not isinstance(rates.get(key), int) or rates[key] <= 0:
                blockers.append(f"Full short generation requires a reviewed positive {key} rate")
        if include_media and backend.get("VIBESHORTS_RENDER_RUNNER") == "local":
            blockers.append("Real-service exports require a Docker or Cloud Run renderer")
    return {"ready": not blockers, "blockers": blockers, "network_checked": False}
