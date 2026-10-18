import base64
import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from execution.config import Settings
from execution.director_environment import prepare_environment
from execution.identity import FirebaseIdentity
from providers.credentials import vertex_credentials
from providers.studio import StudioProvider
from tools.contracts.models import ProjectCreate
from tools.contracts.studio import (
    Composition,
    ConversationInput,
    EditInput,
    MusicInput,
    StudioCommand,
    VideoInput,
)


@pytest.mark.parametrize("duration", [4, 6, 8])
def test_video_reservation_matches_requested_duration(duration):
    settings = split_settings()
    provider = StudioProvider(SimpleNamespace(settings=settings), "video")
    request = VideoInput(prompt="test", first_frame_artifact_id="art_test", source_duration_seconds=duration)
    assert provider.snapshot(request)["reservation_micros"] == duration


@pytest.mark.parametrize(
    "resolution,audio,unit_rate",
    [("720p", False, 30000), ("720p", True, 50000), ("1080p", False, 50000), ("1080p", True, 80000)],
)
def test_video_rate_is_bound_to_model_resolution_and_audio(resolution, audio, unit_rate):
    settings = split_settings(video_model="veo-3.1-lite-generate-001")
    rates = json.loads(settings.rate_json)
    rates["video_per_second_micros"] = 80000
    rates["video_rates"] = {
        settings.video_model: {
            "720p:no_audio": 30000,
            "720p:audio": 50000,
            "1080p:no_audio": 50000,
            "1080p:audio": 80000,
        }
    }
    settings.rate_json = json.dumps(rates)
    request = VideoInput(
        prompt="test",
        first_frame_artifact_id="art_test",
        source_duration_seconds=8,
        resolution=resolution,
        generate_audio=audio,
    )
    provider = StudioProvider(SimpleNamespace(settings=settings), "video")
    assert provider.snapshot(request)["reservation_micros"] == unit_rate * 8
    settings.video_model = "another-model"
    assert provider.snapshot(request)["reservation_micros"] == 80000 * 8


def split_settings(**overrides):
    return Settings(
        GOOGLE_CLOUD_PROJECT="firebase-project",
        vertex_project="vertex-project",
        provider="vertex",
        paid_allowance_micros=1_000_000,
        rate_json=json.dumps(
            {
                "version": "test",
                "verified_at": "2026-10-07",
                "input_per_million_micros": 300000,
                "output_per_million_micros": 30000000,
                "video_per_second_micros": 1,
                "music_per_call_micros": 1,
                "director_reservation_micros": 1,
            }
        ),
        **overrides,
    )


def test_project_environment_and_single_project_fallback(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "firebase-project")
    monkeypatch.delenv("VIBESHORTS_VERTEX_PROJECT", raising=False)
    assert Settings().vertex_cloud_project == "firebase-project"
    monkeypatch.setenv("VIBESHORTS_VERTEX_PROJECT", "vertex-project")
    settings = Settings()
    assert settings.google_cloud_project == "firebase-project"
    assert settings.vertex_cloud_project == "vertex-project"


def test_firebase_identity_stays_in_application_project(monkeypatch):
    import firebase_admin

    seen = {}

    def missing(name):
        seen["name"] = name
        raise ValueError("Not initialized")

    def initialize(**kwargs):
        seen.update(kwargs)
        return "firebase-app"

    monkeypatch.setattr(firebase_admin, "get_app", missing)
    monkeypatch.setattr(firebase_admin, "initialize_app", initialize)
    assert FirebaseIdentity(split_settings()).app == "firebase-app"
    assert seen["options"] == {"projectId": "firebase-project"}
    assert seen["name"] == "firebase-project"


def test_vertex_credentials_are_loaded_separately(monkeypatch):
    import google.auth

    seen = {}
    credentials = object()

    def load(path, **kwargs):
        seen.update(path=path, **kwargs)
        return credentials, "vertex-project"

    monkeypatch.setattr(google.auth, "load_credentials_from_file", load)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/private/firebase.json")
    assert vertex_credentials(split_settings(vertex_credentials="/private/vertex.json")) is credentials
    assert seen["path"] == "/private/vertex.json"
    assert seen["scopes"] == ["https://www.googleapis.com/auth/cloud-platform"]
    assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == "/private/firebase.json"
    assert vertex_credentials(split_settings()) is None


@pytest.mark.parametrize("kind", ["video", "music", "storyboard", "edit"])
def test_media_clients_use_snapshotted_ai_project_and_credentials(monkeypatch, kind):
    from google import genai

    credentials = object()
    seen = {}
    monkeypatch.setattr("providers.studio.vertex_credentials", lambda settings: credentials)

    def client(**kwargs):
        seen.update(kwargs)
        return "client"

    monkeypatch.setattr(genai, "Client", client)
    settings = split_settings()
    provider = StudioProvider(SimpleNamespace(settings=settings), kind)
    snapshot = provider.snapshot()
    settings.vertex_project = "different-new-project"
    assert provider.client(snapshot) == "client"
    assert seen["project"] == "vertex-project"
    assert seen["credentials"] is credentials
    assert settings.google_cloud_project == "firebase-project"
    # Jobs accepted before split routing existed keep the old application-project route.
    snapshot.pop("project")
    provider.client(snapshot)
    assert seen["project"] == "firebase-project"


@pytest.mark.parametrize("audio_key", ["audioContent", "bytesBase64Encoded"])
def test_vertex_music_uses_ai_project_and_credentials(monkeypatch, audio_key):
    from google.auth.transport import requests

    credentials = object()
    seen = {}
    monkeypatch.setattr("providers.studio.vertex_credentials", lambda settings: credentials)

    class Session:
        def __init__(self, credential):
            seen["credentials"] = credential

        def post(self, url, **kwargs):
            seen["url"] = url
            return SimpleNamespace(
                status_code=200,
                json=lambda: {"predictions": [{audio_key: base64.b64encode(b"music").decode()}]},
            )

        def close(self):
            seen["closed"] = True

    monkeypatch.setattr(requests, "AuthorizedSession", Session)
    provider = StudioProvider(SimpleNamespace(settings=split_settings()), "music")
    snapshot = provider.snapshot()
    provider.settings.vertex_project = "changed"
    assert provider._music(MusicInput(prompt="instrumental"), snapshot).data == b"music"
    assert "/projects/vertex-project/locations/" in seen["url"]
    assert seen["credentials"] is credentials and seen["closed"]


def test_video_source_download_uses_vertex_credentials(monkeypatch):
    from google.cloud import storage

    credentials = object()
    seen = {}
    monkeypatch.setattr("providers.studio.vertex_credentials", lambda settings: credentials)
    blob = SimpleNamespace(
        size=5, generation=7, reload=lambda: None, download_as_bytes=lambda **kwargs: b"video"
    )

    def client(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(bucket=lambda bucket: SimpleNamespace(blob=lambda key: blob))

    monkeypatch.setattr(storage, "Client", client)
    result = SimpleNamespace(
        name="operation",
        done=True,
        error=None,
        response=SimpleNamespace(
            generated_videos=[
                SimpleNamespace(video=SimpleNamespace(video_bytes=None, uri="gs://output/v.mp4"))
            ]
        ),
    )
    provider = StudioProvider(SimpleNamespace(settings=split_settings()), "video")
    monkeypatch.setattr(
        provider,
        "client",
        lambda snapshot: SimpleNamespace(
            operations=SimpleNamespace(get=lambda op: result), close=lambda: None
        ),
    )
    output, _ = provider.poll_video({"name": "operation"}, provider.snapshot())
    assert output.data == b"video"
    assert seen == {"project": "vertex-project", "credentials": credentials}


def test_director_payload_keeps_application_and_model_projects_separate(monkeypatch):
    seen = {}

    def run(args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(returncode=0, stdout=Composition(duration_seconds=2).model_dump_json())

    monkeypatch.setattr("providers.studio.subprocess.run", run)
    provider = StudioProvider(
        SimpleNamespace(settings=split_settings(vertex_credentials="/private/vertex.json")), "edit"
    )
    job = {"caller": {"uid": "alice"}, "project_id": "p", "run_id": "r", "job_id": "j", "brand_version": None}
    request = EditInput(instruction="mute", expected_head="a")
    provider._director(request, provider.snapshot(), job)
    payload = json.loads(seen["input"])
    assert payload["cloud_project"] == "firebase-project"
    assert payload["vertex_project"] == "vertex-project"
    assert seen["env"]["VIBESHORTS_VERTEX_CREDENTIALS"] == "/private/vertex.json"
    assert "/private/vertex.json" not in seen["input"]


@pytest.mark.parametrize(
    "failure,status,code",
    [
        (FileNotFoundError("missing Python"), "failed", "DIRECTOR_UNAVAILABLE"),
        (PermissionError("Python is not executable"), "failed", "DIRECTOR_UNAVAILABLE"),
        (OSError("subprocess I/O failed"), "submission_unknown", "PROVIDER_SUBMISSION_UNCERTAIN"),
        (subprocess.TimeoutExpired("director", 90), "submission_unknown", "PROVIDER_SUBMISSION_UNCERTAIN"),
    ],
)
def test_director_start_failure_releases_budget_but_timeout_stays_uncertain(
    runtime, alice, monkeypatch, failure, status, code
):
    commands = runtime.commands
    commands.settings = split_settings()
    project = commands.create_project(
        alice, ProjectCreate(name="Director failure", idempotency_key="director-failure")
    ).data["project_id"]
    handle = commands.submit_job(
        alice,
        StudioCommand(
            project_id=project,
            idempotency_key="turn",
            input=ConversationInput(instruction="A robot story"),
        ),
        "director_turn",
    )

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr("providers.studio.subprocess.run", fail)
    runtime.worker.execute(project, handle.job_id)
    job = commands.get_job(alice, project, handle.job_id)
    assert job.status == status
    assert job.error.code == code
    uncertain = status == "submission_unknown"
    assert job.costs["uncertain"] == uncertain
    assert job.costs["reserved_micros"] == int(uncertain)
    assert job.costs["settled_micros"] == 0
    assert commands.repo.get("budgets/account")["reserved_micros"] == int(uncertain)
    assert commands.repo.get("budgets/" + project)["reserved_micros"] == int(uncertain)
    if not uncertain:
        assert job.error.retryable


@pytest.mark.parametrize("separate_credentials", [False, True])
def test_director_firestore_binds_application_adc_before_model_switch(monkeypatch, separate_credentials):
    import google.auth
    from google.auth.credentials import AnonymousCredentials

    application_credentials = AnonymousCredentials()
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/private/firebase.json")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "firebase-project")
    monkeypatch.delenv("VIBESHORTS_VERTEX_CREDENTIALS", raising=False)
    if separate_credentials:
        monkeypatch.setenv("VIBESHORTS_VERTEX_CREDENTIALS", "/private/vertex.json")

    def default(**kwargs):
        assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == "/private/firebase.json"
        assert os.environ["GOOGLE_CLOUD_PROJECT"] == "firebase-project"
        return application_credentials, "firebase-project"

    monkeypatch.setattr(google.auth, "default", default)
    # Register mutated model environment with monkeypatch so it is restored after the test.
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
    repo = prepare_environment(
        {
            "cloud_project": "firebase-project",
            "vertex_project": "vertex-project",
            "route": "vertex",
            "location": "global",
        }
    )
    assert repo.client.project == "firebase-project"
    assert repo.client._credentials is application_credentials
    assert os.environ["GOOGLE_CLOUD_PROJECT"] == "vertex-project"
    assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == (
        "/private/vertex.json" if separate_credentials else "/private/firebase.json"
    )
