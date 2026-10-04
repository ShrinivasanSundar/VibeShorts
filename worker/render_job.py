"""Renderer credential boundary: fetch/store outside the browser subprocess."""

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

from google.cloud import storage

from tools.composition.package import unpack
from tools.media.pipeline import inspect


def blob(client, uri):
    if not uri.startswith("gs://"):
        raise ValueError("Only private storage objects are accepted")
    bucket, key = uri[5:].split("/", 1)
    return client.bucket(bucket).blob(key)


def main():
    client = storage.Client()
    source = blob(client, os.environ["VIBESHORTS_RENDER_PACKAGE"])
    source.reload()
    if source.size > 250_000_000:
        raise ValueError("Package exceeds limit")
    data = source.download_as_bytes(if_generation_match=source.generation)
    if hashlib.sha256(data).hexdigest() != os.environ["VIBESHORTS_RENDER_HASH"]:
        raise ValueError("Package hash mismatch")
    with tempfile.TemporaryDirectory() as folder:
        manifest, _ = unpack(data, folder)
        output = Path(folder) / "result.mp4"
        quality = os.environ["VIBESHORTS_RENDER_QUALITY"]
        if quality not in {"draft", "final"}:
            raise ValueError("Invalid quality")
        # The child has no application credentials or project environment. Packages
        # contain only server-generated markup and pinned local runtime/media files.
        subprocess.run(
            [
                "/app/node_modules/.bin/hyperframes",
                "render",
                folder,
                "--output",
                str(output),
                "--browser-path",
                "/usr/local/bin/hyperframes-chrome",
                "--fps",
                "24",
                "--quality",
                "draft" if quality == "draft" else "delivery",
            ],
            env={"PATH": os.environ["PATH"], "HOME": "/tmp", "HYPERFRAMES_TELEMETRY_DISABLED": "1"},
            check=True,
            timeout=840,
        )
        content = output.read_bytes()
        facts = inspect(content, "video/mp4")
        profile = manifest["output_profile"]
        if (facts["width"], facts["height"], round(facts["fps"])) != (
            profile["width"],
            profile["height"],
            24,
        ):
            raise ValueError("Render profile mismatch")
        if abs(facts["duration_seconds"] - profile["duration_seconds"]) > 0.15:
            raise ValueError("Render duration mismatch")
        destination = blob(client, os.environ["VIBESHORTS_RENDER_OUTPUT"])
        destination.metadata = {"content_sha256": facts["content_sha256"]}
        destination.upload_from_string(content, content_type="video/mp4", if_generation_match=0)


if __name__ == "__main__":
    main()
