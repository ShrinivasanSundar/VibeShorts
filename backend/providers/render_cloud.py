"""Cloud Run Job submission happens once; subsequent deliveries only poll its handle."""

import re

from providers.image import ImageOutput, ProviderFailure
from tools.contracts.errors import AppError


def session():
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return AuthorizedSession(credentials)


def submit(commands, request, job):
    name = job["provider"].get("render_cloud_job") or commands.settings.render_cloud_job
    if not name or not re.fullmatch(r"projects/[\w-]+/locations/[\w-]+/jobs/[\w-]+", name):
        raise AppError("RENDER_UNAVAILABLE", "Configure a Cloud Run renderer job", 503)
    artifact = commands._artifact(job["project_id"], request.composition_artifact_id)
    output = f"projects/{job['project_id']}/jobs/{job['job_id']}/render/result.mp4"
    env = {
        "VIBESHORTS_RENDER_PACKAGE": artifact["storage_uri"],
        "VIBESHORTS_RENDER_OUTPUT": commands.storage.uri(output),
        "VIBESHORTS_RENDER_HASH": artifact["content_sha256"],
        "VIBESHORTS_RENDER_QUALITY": request.quality,
    }
    with session() as client:
        response = client.post(
            "https://run.googleapis.com/v2/" + name + ":run",
            json={
                "overrides": {
                    "taskCount": 1,
                    "timeout": "900s",
                    "containerOverrides": [{"env": [{"name": k, "value": v} for k, v in env.items()]}],
                }
            },
            timeout=90,
        )
        if response.status_code >= 400:
            raise ProviderFailure(
                "RENDER_SUBMISSION_FAILED",
                "Renderer submission failed",
                uncertain=response.status_code >= 500,
            )
        operation = response.json()
        if not operation.get("name"):
            raise ProviderFailure("MISSING_OPERATION", "Renderer omitted its handle", uncertain=True)
        return {"name": operation["name"], "output_path": output}


def poll(commands, operation):
    if not re.fullmatch(r"projects/[\w-]+/locations/[\w-]+/operations/[\w-]+", operation["name"]):
        raise AppError("INVALID_OPERATION", "Invalid stored renderer operation")
    with session() as client:
        response = client.get("https://run.googleapis.com/v2/" + operation["name"], timeout=30)
        response.raise_for_status()
        result = response.json()
    if not result.get("done"):
        return None, operation
    if result.get("error"):
        raise ProviderFailure("RENDER_FAILED", "Renderer execution failed")
    stored = commands.storage.get(operation["output_path"])
    if not stored:
        raise ProviderFailure("MISSING_RENDER", "Renderer completed without a durable result")
    return ImageOutput(stored[0], "video/mp4"), operation
