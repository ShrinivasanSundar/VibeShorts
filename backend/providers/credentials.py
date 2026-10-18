"""Optional Vertex credentials, separate from application ADC."""

from pathlib import Path


def vertex_credentials(settings):
    if not settings.vertex_credentials:
        return None
    import google.auth

    credentials, _ = google.auth.load_credentials_from_file(
        str(Path(settings.vertex_credentials).expanduser()),
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    return credentials
