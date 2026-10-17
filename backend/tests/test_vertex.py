import pytest

from execution.config import Settings
from providers.image import ProviderFailure, VertexImageProvider
from tools.contracts.models import ImageInput


def settings():
    return Settings(
        provider="vertex",
        paid_allowance_micros=1_000_000,
        rate_json=(
            '{"version":"test-v1","verified_at":"2026-10-03",'
            '"input_per_million_micros":300000,"output_per_million_micros":30000000}'
        ),
    )


@pytest.mark.parametrize("vertex_project", [None, "separate-vertex-project"])
def test_vertex_client_snapshots_route_disables_transport_retries_and_extracts_bytes(
    monkeypatch, png, vertex_project
):
    from google import genai
    from google.genai import types

    seen = {}
    credentials = object()
    monkeypatch.setattr("providers.image.vertex_credentials", lambda settings: credentials)

    class Client:
        def __init__(self, **kwargs):
            seen.update(kwargs)
            self.models = self

        def generate_content(self, **kwargs):
            seen.update(kwargs)
            return types.GenerateContentResponse(
                candidates=[
                    types.Candidate(
                        content=types.Content(
                            parts=[
                                # Interim thinking images must not count as the result.
                                types.Part(
                                    inline_data=types.Blob(data=b"draft", mime_type="image/png"), thought=True
                                ),
                                types.Part.from_bytes(data=png, mime_type="image/png"),
                            ]
                        )
                    )
                ],
                usage_metadata=types.GenerateContentResponseUsageMetadata(
                    prompt_token_count=10, candidates_token_count=1290
                ),
            )

        def close(self):
            seen["closed"] = True

    monkeypatch.setattr(genai, "Client", Client)
    config = settings()
    config.vertex_project = vertex_project
    provider = VertexImageProvider(config)
    snapshot = provider.snapshot()
    # Accepted jobs keep their AI project when deployment settings change.
    config.vertex_project = "changed-after-acceptance"
    output = provider.generate(ImageInput(prompt="Reveal"), [png], snapshot)
    assert output.data == png
    assert seen["vertexai"] and seen["location"] == snapshot["location"]
    assert seen["project"] == (vertex_project or config.google_cloud_project)
    assert seen["credentials"] is credentials
    assert seen["http_options"].retry_options.attempts == 1
    assert seen["config"].image_config.aspect_ratio == "9:16"
    assert seen["closed"]
    assert provider.cost(output.usage, snapshot) == (38703, "usage_estimate")
    assert not snapshot["deprecated"] and snapshot["launch_stage"] == "preview"


@pytest.mark.parametrize(
    "case,code,uncertain",
    [
        ("filtered", "SAFETY_REJECTED", False),
        ("empty", "INVALID_PROVIDER_OUTPUT", True),
        ("timeout", "PROVIDER_SUBMISSION_UNCERTAIN", True),
        ("quota", "PROVIDER_UNAVAILABLE", False),
    ],
)
def test_vertex_filtered_missing_and_transport_failure_classification(monkeypatch, case, code, uncertain):
    from google import genai
    from google.genai import types

    class Error(Exception):
        code = 429

    class Client:
        def __init__(self, **kwargs):
            self.models = self

        def generate_content(self, **kwargs):
            if case == "timeout":
                raise TimeoutError()
            if case == "quota":
                raise Error()
            if case == "filtered":
                return types.GenerateContentResponse(
                    prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason="SAFETY")
                )
            return types.GenerateContentResponse()

        def close(self):
            pass

    monkeypatch.setattr(genai, "Client", Client)
    provider = VertexImageProvider(settings())
    with pytest.raises(ProviderFailure) as exc:
        provider.generate(ImageInput(prompt="Reveal"), [], provider.snapshot())
    assert exc.value.payload.code == code
    assert exc.value.uncertain == uncertain


def test_live_calls_require_allowance_and_rate_profile():
    with pytest.raises(ValueError):
        Settings(provider="vertex")


@pytest.mark.paid
@pytest.mark.skipif(
    __import__("os").getenv("VIBESHORTS_RUN_PAID_SMOKE") != "1", reason="Explicit paid opt-in required"
)
def test_single_paid_image_smoke():
    import hashlib
    import os

    from execution.runtime import Runtime
    from tools.contracts.models import ImageCommand, ProjectCreate

    runtime = Runtime.create()
    assert runtime.commands.settings.provider == "vertex"
    caller = runtime.commands.identity.verify(os.environ["VIBESHORTS_SMOKE_FIREBASE_ID_TOKEN"])
    project = runtime.commands.create_project(
        caller, ProjectCreate(name="Paid acceptance", idempotency_key="paid-smoke-project")
    ).data["project_id"]
    handle = runtime.commands.generate_image(
        caller,
        ImageCommand(
            project_id=project,
            idempotency_key="paid-smoke-image",
            input=ImageInput(prompt="A blue geometric product pedestal, studio lighting, no text"),
        ),
    )
    runtime.worker.execute(project, handle.job_id)
    result = runtime.commands.get_job(caller, project, handle.job_id)
    assert result.status == "succeeded", result.error
    job_path = f"projects/{project}/jobs/{handle.job_id}"
    assert runtime.commands.repo.get(job_path)["attempt"] == 1
    artifact = runtime.commands.get_asset(caller, project, result.artifact_ids[0]).data
    content, mime_type = runtime.commands.asset_content(caller, project, result.artifact_ids[0])
    assert mime_type in {"image/png", "image/jpeg"}
    assert hashlib.sha256(content).hexdigest() == artifact["content_sha256"]
    assert not runtime.worker.execute(project, handle.job_id)
    assert runtime.commands.repo.get(job_path)["attempt"] == 1
