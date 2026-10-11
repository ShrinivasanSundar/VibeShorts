import json
from functools import cached_property
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from execution.paths import BACKEND_ROOT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VIBESHORTS_", extra="ignore")
    mode: Literal["emulator", "production"] = "emulator"
    local_live: bool = False
    google_cloud_project: str = Field(default="demo-vibeshorts", validation_alias="GOOGLE_CLOUD_PROJECT")
    vertex_project: str | None = Field(default=None, min_length=1)
    vertex_credentials: str | None = Field(default=None, min_length=1)
    bucket: str = "demo-vibeshorts.appspot.com"
    public_url: str = "http://127.0.0.1:8000"
    web_url: str = "http://127.0.0.1:3000"
    provider: Literal["fixture", "vertex", "developer"] = "fixture"
    image_model: str = "gemini-2.5-flash-image"
    google_location: str = "global"
    video_model: str = "veo-3.1-generate-001"
    video_generate_audio: bool = True
    developer_video_model: str = "veo-3.1-generate-preview"
    developer_music_model: str = "lyria-3-clip-preview"
    video_location: str = "us-central1"
    music_model: str = "lyria-002"
    music_location: str = "global"
    director_model: str = "gemini-2.5-flash"
    developer_api_key: str | None = None
    adk_python: str = str(BACKEND_ROOT / "agents/creative_director/.venv/bin/python")
    render_runner: Literal["docker", "local", "cloud_run"] = "docker"
    render_cloud_job: str | None = None
    render_image: str = "vibeshorts-render:local"
    max_media_bytes: int = Field(default=200_000_000, ge=20_000_000, le=500_000_000)
    project_cap_micros: int = Field(default=1_000_000, ge=0)
    paid_allowance_micros: int = Field(default=0, ge=0)
    rate_json: str | None = None
    topic: str = "vibeshorts-jobs"
    lease_seconds: int = Field(default=180, ge=30)
    provider_timeout_seconds: int = Field(default=90, ge=1, le=120)
    internal_audience: str | None = None
    internal_service_emails: str = ""
    oauth_clients_json: str | None = None
    stdio_firebase_id_token: str | None = None
    stdio_projects: str = ""
    stdio_scopes: str = ""

    @model_validator(mode="after")
    def validate_environment(self):
        import os
        from urllib.parse import urlparse

        if self.provider_timeout_seconds >= self.lease_seconds:
            raise ValueError("Provider timeout must be shorter than the worker lease")
        if self.local_live and self.mode != "production":
            raise ValueError("Local live testing requires production mode")
        if self.mode == "production":
            if any(
                os.getenv(k)
                for k in (
                    "FIREBASE_AUTH_EMULATOR_HOST",
                    "FIRESTORE_EMULATOR_HOST",
                    "STORAGE_EMULATOR_HOST",
                    "PUBSUB_EMULATOR_HOST",
                )
            ):
                raise ValueError("Emulator variables are forbidden in production")
            if self.google_cloud_project.startswith("demo-") or self.provider not in {"vertex", "developer"}:
                raise ValueError("Production requires a real cloud project and Vertex provider")
            if self.provider == "vertex" and self.vertex_cloud_project.startswith("demo-"):
                raise ValueError("Production requires a real Vertex project")
            urls = [urlparse(u) for u in (self.public_url, self.web_url)]
            if self.local_live:
                if any(
                    u.scheme not in {"http", "https"}
                    or u.hostname not in {"localhost", "127.0.0.1", "::1"}
                    or u.username is not None
                    or u.password is not None
                    or u.path not in {"", "/"}
                    or u.query
                    or u.fragment
                    for u in urls
                ):
                    raise ValueError("Local live URLs must be loopback origins")
            elif any(u.scheme != "https" for u in urls):
                raise ValueError("Production URLs must use HTTPS")
            if not self.local_live and (not self.internal_audience or not self.internal_service_emails):
                raise ValueError("Production requires internal service identity configuration")
        if self.provider in {"vertex", "developer"}:
            if self.paid_allowance_micros <= 0 or not self.rate_json:
                raise ValueError("Vertex requires a positive paid allowance and a reviewed rate profile")
            if self.provider == "developer" and not self.developer_api_key:
                raise ValueError("Developer route requires an explicit server API key")
            rate = json.loads(self.rate_json)
            for key in ("version", "verified_at", "input_per_million_micros", "output_per_million_micros"):
                if key not in rate:
                    raise ValueError(f"Rate profile missing {key}")
            if rate["input_per_million_micros"] < 0 or rate["output_per_million_micros"] <= 0:
                raise ValueError("Rates must be nonnegative with a positive output rate")
        return self

    @property
    def vertex_cloud_project(self) -> str:
        """Keep existing single-project deployments compatible."""
        return self.vertex_project or self.google_cloud_project

    @cached_property
    def clients(self) -> dict:
        if self.oauth_clients_json:
            return json.loads(self.oauth_clients_json)
        return {
            "vibeshorts-sdk": {"name": "VibeShorts SDK", "redirect_uris": ["http://127.0.0.1:8765/callback"]},
            "vibeshorts-inspector": {
                "name": "MCP Inspector",
                "redirect_uris": [
                    "http://localhost:6274/oauth/callback",
                    "http://localhost:6274/oauth/callback/debug",
                    "http://127.0.0.1:6276/oauth/callback",
                ],
            },
        }
