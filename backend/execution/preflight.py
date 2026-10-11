"""Offline preparation checks; never initialize cloud clients or submit work."""

import os
from pathlib import Path

from pydantic import ValidationError

from execution.config import Settings
from execution.integrations import placeholder
from providers.image import VertexImageProvider


def paid_smoke_preflight():
    blockers = []
    try:
        settings = Settings()
    except ValidationError as exc:
        # Pydantic's full error includes inputs, which can contain credentials.
        return {
            "ready": False,
            "blockers": [error["msg"] for error in exc.errors()],
            "network_checked": False,
        }
    if settings.mode != "production" or settings.provider != "vertex":
        blockers.append("Set production mode and the Vertex provider in an isolated environment")
    for name, value in (
        ("cloud project", settings.google_cloud_project),
        ("Vertex project", settings.vertex_cloud_project),
        ("private bucket", settings.bucket),
        ("public API URL", settings.public_url),
        ("web URL", settings.web_url),
        ("internal service identities", settings.internal_service_emails),
    ):
        if placeholder(value) or value.startswith("demo-"):
            blockers.append(f"Configure a real {name}")
    configured_credentials = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    adc_path = (
        Path(configured_credentials).expanduser()
        if configured_credentials
        else Path(os.getenv("CLOUDSDK_CONFIG", str(Path.home() / ".config/gcloud")))
        / "application_default_credentials.json"
    )
    if not adc_path.is_file():
        blockers.append("Provide local ADC credentials (gcloud auth application-default login)")
    if settings.vertex_credentials and not Path(settings.vertex_credentials).expanduser().is_file():
        blockers.append("Provide an existing Vertex credential file")
    if not os.getenv("VIBESHORTS_SMOKE_FIREBASE_ID_TOKEN"):
        blockers.append("Provide a current Firebase ID token for the real Firebase project")
    reservation = None
    if settings.provider == "vertex":
        reservation = VertexImageProvider(settings).snapshot()["reservation_micros"]
        if min(settings.project_cap_micros, settings.paid_allowance_micros) < reservation:
            blockers.append("Project and account allowances must cover the single-image reservation")
    return {
        "ready": not blockers,
        "blockers": blockers,
        "network_checked": False,
        "model": settings.image_model,
        "application_project": settings.google_cloud_project,
        "vertex_project": settings.vertex_cloud_project,
        "reservation_micros": reservation,
        "note": (
            "Offline only: cloud permissions, private bucket policy, "
            "model availability and billing remain unverified"
        ),
    }
