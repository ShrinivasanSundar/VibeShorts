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
from execution.director_schema import DirectorStoryboard, DirectorComposition, DirectorConversation
from tools.contracts.studio import MusicInput, Scene
client = genai.Client(vertexai=True, project='offline', location='global', credentials=AnonymousCredentials())
try:
    for schema in (DirectorStoryboard, DirectorComposition, DirectorConversation):
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


def test_beginner_director_with_no_brand_returns_without_tool_loop():
    interpreter = BACKEND_ROOT / "agents/creative_director/.venv/bin/python"
    if not interpreter.exists():
        pytest.skip("Isolated director environment is not installed")
    result = subprocess.run(
        [
            str(interpreter),
            "-c",
            """
import asyncio, io, json, runpy, sys
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from execution.repository import MemoryRepository
from execution.paths import BACKEND_ROOT
from tools.contracts.studio import DirectorTurn

requests = []
class OfflineModel(BaseLlm):
    async def generate_content_async(self, llm_request, stream=False):
        requests.append(llm_request)
        assert not llm_request.tools_dict
        assert llm_request.config.response_schema is not None
        prompt = json.loads(llm_request.contents[-1].parts[0].text)
        assert prompt['brand_dna'] == {}
        reply = DirectorTurn(action='clarify', text='What video would you like to make?')
        yield LlmResponse(content=types.Content(role='model', parts=[
            types.Part(text=reply.model_dump_json())
        ]))

repo = MemoryRepository()
repo.documents.update({
    'users/alice': {'access_enabled': True},
    'projects/p': {'members': {'alice': 'owner'}},
    'projects/p/jobs/j': {'caller': {'uid': 'alice'}, 'run_id': 'r'},
})
namespace = runpy.run_path(str(BACKEND_ROOT / 'agents/creative_director/direct.py'), run_name='offline_test')
main = namespace['main']
main.__globals__['prepare_environment'] = lambda payload: repo
main.__globals__['Gemini'] = lambda **kwargs: OfflineModel(model='offline-director')
sys.stdin = io.StringIO(json.dumps({
    'operation': 'director_turn', 'project_id': 'p', 'uid': 'alice', 'run_id': 'r', 'job_id': 'j',
    'model': 'offline-director', 'brand_version': None, 'request': {'context': {}}
}))
asyncio.run(main())
assert len(requests) == 1
""",
        ],
        env={**os.environ, "PYTHONPATH": str(BACKEND_ROOT)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "What video would you like to make?" in result.stdout
