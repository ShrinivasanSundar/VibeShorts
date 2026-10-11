"""Exercise the actual isolated SDK's schema conversion without paid requests."""

import os
import subprocess

import pytest

from execution.paths import BACKEND_ROOT


def test_director_schemas_convert_in_isolated_sdk():
    interpreter = BACKEND_ROOT / "agents/creative_director/.venv/bin/python"
    if not interpreter.exists():
        pytest.skip("Isolated director environment is not installed")
    result = subprocess.run(
        [
            str(interpreter),
            "-c",
            """
from google import genai
from google.auth.credentials import AnonymousCredentials
from google.genai import _transformers
from pydantic import ValidationError
from execution.director_schema import DirectorStoryboard, DirectorComposition
from tools.contracts.studio import MusicInput, Scene
client = genai.Client(vertexai=True, project='offline', location='global', credentials=AnonymousCredentials())
try:
    for schema in (DirectorStoryboard, DirectorComposition):
        assert _transformers.t_schema(client._api_client, schema)
finally:
    client.close()
for schema, value in [
    (MusicInput, {'prompt': 'music', 'instrumental': False}),
    (Scene, {'id': 's', 'objective': 'test', 'visual_prompt': 'test',
             'editorial_duration_seconds': 0}),
]:
    try:
        schema.model_validate(value)
    except ValidationError:
        continue
    raise AssertionError('Strict final contract must reject invalid output')
""",
        ],
        env={**os.environ, "PYTHONPATH": str(BACKEND_ROOT)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
