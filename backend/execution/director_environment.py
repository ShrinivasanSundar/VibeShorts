"""Bind application storage before selecting the isolated director's model credentials."""

import os
from pathlib import Path

from execution.repository import FirestoreRepository


def prepare_environment(payload):
    # Firestore's client captures application ADC before the model environment changes.
    repo = FirestoreRepository(payload["cloud_project"])
    if payload["route"] == "vertex":
        os.environ.update(
            GOOGLE_GENAI_USE_VERTEXAI="TRUE",
            GOOGLE_CLOUD_PROJECT=payload.get("vertex_project") or payload["cloud_project"],
            GOOGLE_CLOUD_LOCATION=payload["location"],
        )
        if os.getenv("VIBESHORTS_VERTEX_CREDENTIALS"):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(
                Path(os.environ["VIBESHORTS_VERTEX_CREDENTIALS"]).expanduser()
            )
    else:
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "FALSE"
        os.environ["GOOGLE_API_KEY"] = os.environ["VIBESHORTS_DIRECTOR_API_KEY"]
    return repo
