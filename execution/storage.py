import hashlib
import io
import json
import warnings
from datetime import timedelta

from PIL import Image

from tools.contracts.errors import AppError

MAX_UPLOAD = 7_000_000
MAX_OUTPUT = 20_000_000
Image.MAX_IMAGE_PIXELS = 40_000_000


def inspect_image(data: bytes, mime_type: str | None = None, limit: int = MAX_OUTPUT) -> dict:
    if not data or len(data) > limit:
        raise AppError("INVALID_MEDIA", "Image exceeds the permitted size")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"PNG", "JPEG"}:
                    raise ValueError("Unsupported image encoding")
                actual_mime = Image.MIME[image.format]
                if mime_type and actual_mime != mime_type:
                    raise ValueError("MIME type does not match image content")
                width, height = image.size
                image.verify()
            # verify() alone does not fully decode JPEG pixel data.
            with Image.open(io.BytesIO(data)) as decoded:
                decoded.load()
    except Exception as exc:
        raise AppError("INVALID_MEDIA", "A valid PNG or JPEG image is required") from exc
    return {
        "width": width,
        "height": height,
        "mime_type": actual_mime,
        "size_bytes": len(data),
        "content_sha256": hashlib.sha256(data).hexdigest(),
    }


class MemoryStorage:
    def __init__(self):
        self.objects = {}

    def put(self, path: str, data: bytes, metadata: dict):
        if path in self.objects:
            existing, _ = self.objects[path]
            if existing != data:
                raise AppError("REVISION_CONFLICT", "Object is immutable", 409)
            return
        self.objects[path] = (data, metadata.copy())

    def get(self, path: str):
        return self.objects.get(path)

    def uri(self, path: str):
        return "memory://" + path


class CloudStorage:
    def __init__(self, settings):
        from google.cloud import storage

        self.settings = settings
        self.client = storage.Client(project=settings.google_cloud_project)
        self.bucket = self.client.bucket(settings.bucket)

    def put(self, path: str, data: bytes, metadata: dict):
        from google.api_core.exceptions import PreconditionFailed

        blob = self.bucket.blob(path)
        blob.metadata = {"vibeshorts": json.dumps(metadata, separators=(",", ":"))}
        try:
            blob.upload_from_string(data, content_type=metadata["mime_type"], if_generation_match=0)
        except PreconditionFailed as exc:
            existing = self.get(path)
            if not existing or hashlib.sha256(existing[0]).digest() != hashlib.sha256(data).digest():
                raise AppError("REVISION_CONFLICT", "Object is immutable", 409) from exc

    def get(self, path: str):
        from google.api_core.exceptions import NotFound

        blob = self.bucket.blob(path)
        try:
            blob.reload()
            if blob.size > self.settings.max_media_bytes:
                raise AppError("INVALID_MEDIA", "Stored image exceeds permitted size")
            metadata = json.loads((blob.metadata or {}).get("vibeshorts", "{}"))
            return blob.download_as_bytes(if_generation_match=blob.generation), metadata
        except NotFound:
            return None

    def uri(self, path: str):
        return f"gs://{self.settings.bucket}/{path}"

    def signed_url(self, path: str, method="GET", mime_type=None):
        import google.auth
        from google.auth.transport.requests import Request

        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        kwargs = {}
        if not hasattr(credentials, "sign_bytes"):
            credentials.refresh(Request())
            email = getattr(credentials, "service_account_email", None)
            if not email or email == "default":
                raise AppError("STORAGE_UNAVAILABLE", "ADC must provide a signing service identity", 503)
            kwargs = {"service_account_email": email, "access_token": credentials.token}
        headers = {"x-goog-if-generation-match": "0"} if method == "PUT" else None
        return self.bucket.blob(path).generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=5),
            method=method,
            content_type=mime_type,
            headers=headers,
            credentials=credentials,
            **kwargs,
        )
