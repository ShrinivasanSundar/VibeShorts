"""One resumable ADK Creative Director in a dependency-isolated process."""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig
from google.adk.apps import App, ResumabilityConfig
from google.adk.models.google_llm import Gemini
from google.adk.runners import Runner
from google.genai import types

from execution.director_environment import prepare_environment
from execution.director_schema import DirectorComposition, DirectorStoryboard
from execution.paths import BACKEND_ROOT
from sessions.firestore.bridge import JobResultBridge
from sessions.firestore.service import FirestoreSessionService
from tools.contracts.studio import Composition, Storyboard


async def main():
    payload = json.loads(sys.stdin.read())
    repo = prepare_environment(payload)
    sessions = FirestoreSessionService(repo, payload["project_id"], payload["uid"])
    session_id = (
        "session_"
        + hashlib.sha256((payload["project_id"] + payload["uid"] + payload["run_id"]).encode()).hexdigest()
    )
    session = await sessions.get_session(app_name="vibeshorts", user_id=payload["uid"], session_id=session_id)
    if not session:
        session = await sessions.create_session(
            app_name="vibeshorts",
            user_id=payload["uid"],
            session_id=session_id,
            state={"run_id": payload["run_id"], "project_id": payload["project_id"]},
        )

    bridge = JobResultBridge(sessions)
    session_path = sessions._path("vibeshorts", payload["uid"], session_id)
    for pending in repo.list(session_path + "/pending_calls"):
        await bridge.deliver(session_id, pending["call_id"])

    def get_brand_dna():
        sessions._authorize()
        return (
            repo.get("projects/" + payload["project_id"] + "/brands/" + payload["brand_version"])
            if payload["brand_version"]
            else {}
        )

    editing = payload.get("operation") == "edit"
    schema = Composition if editing else Storyboard
    director = LlmAgent(
        name="creative_director",
        model=Gemini(model=payload["model"], retry_options=types.HttpRetryOptions(attempts=1)),
        instruction=(
            "Edit only the provided typed timeline according to the instruction. Preserve artifact ids and "
            "Preserve clip settings. Return a valid Composition. Never approve it or replace original media."
            if editing
            else (BACKEND_ROOT / "skills/product_launch/director.md").read_text()
        ),
        output_schema=DirectorComposition if editing else DirectorStoryboard,
        output_key="storyboard",
        tools=[get_brand_dna],
        generate_content_config=types.GenerateContentConfig(temperature=0.4, max_output_tokens=4096),
    )
    app = App(
        name="vibeshorts", root_agent=director, resumability_config=ResumabilityConfig(is_resumable=True)
    )
    runner = Runner(app=app, session_service=sessions)
    async for event in runner.run_async(
        user_id=payload["uid"],
        session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=json.dumps(payload))]),
        run_config=RunConfig(max_llm_calls=3),
    ):

        def correlate(tx, event=event):
            path = f"projects/{payload['project_id']}/jobs/{payload['job_id']}"
            job = tx.get(path)
            if not job or job["caller"]["uid"] != payload["uid"] or job["run_id"] != payload["run_id"]:
                raise PermissionError("Director correlation mismatch")
            job["director"] = {
                "session_id": session_id,
                "invocation_id": event.invocation_id,
                "last_event_id": event.id,
                "version": session.state.get("_vibeshorts_version"),
            }
            tx.set(path, job)

        repo.atomic(correlate)
        if event.is_final_response() and event.content:
            text = "".join(part.text or "" for part in event.content.parts)
            storyboard = schema.model_validate_json(text)
            if not editing and (
                storyboard.project_id != payload["project_id"]
                or storyboard.brand_version != payload["brand_version"]
            ):
                raise ValueError("Director changed trusted context")
            print(storyboard.model_dump_json())
            await runner.close()
            return
    await runner.close()
    raise RuntimeError("Director produced no typed plan")


asyncio.run(main())
