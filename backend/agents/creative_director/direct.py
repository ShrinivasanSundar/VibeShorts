"""One resumable ADK Creative Director in a dependency-isolated process."""

import asyncio
import base64
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
from execution.director_schema import DirectorComposition, DirectorConversation, DirectorStoryboard
from execution.paths import BACKEND_ROOT
from sessions.firestore.bridge import JobResultBridge
from sessions.firestore.service import FirestoreSessionService
from tools.contracts.studio import Composition, DirectorTurn, Storyboard


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
    chatting = payload.get("operation") == "director_turn"
    if chatting:
        # Empty brand results can cause repeated tool calls. Bind this trusted
        # context once and use the model's native structured-response schema.
        payload["brand_dna"] = get_brand_dna() or {}
    schema = DirectorTurn if chatting else Composition if editing else Storyboard
    images = payload.pop("reference_images", [])
    parts = [types.Part(text=json.dumps(payload))]
    for image in images:
        parts.append(types.Part(text="Reference image " + image["artifact_id"] + ":"))
        parts.append(types.Part.from_bytes(data=base64.b64decode(image["data"]), mime_type="image/jpeg"))
    grounding = (
        " The user's reference images follow the request, each labelled with its artifact id. "
        "Look at them: they show the exact subject, product, character or style to use. Describe its "
        "real appearance (shape, colours, materials, distinguishing details) in the matching asset's "
        "description and list its artifact id in that asset's reference_artifact_ids. "
        "Keep the story about what the images show."
        if images
        else ""
    )
    director = LlmAgent(
        name="creative_director",
        model=Gemini(model=payload["model"], retry_options=types.HttpRetryOptions(attempts=1)),
        instruction=(
            "You are a friendly video director in a beginner chat. Return a DirectorTurn "
            "with concise, plain-language text. "
            "Use context.history, context.storyboard, context.composition, and context.settings in request. "
            "Brand settings are supplied in brand_dna; an empty object means no brand is configured. "
            "Choose status for questions; clarify when the target or request is ambiguous. "
            "For ideas or storyboard and scene revisions, return action storyboard and the "
            "complete revised Storyboard. Style or motion changes require a storyboard action, "
            "never an instant composition filter. "
            "Respect settings.creative_preferences and policy. Explain which scenes need regeneration; "
            "human approval is required. "
            "Preserve unchanged scene ids, prompts and references. For copy-only edits "
            "preserve visual prompts exactly. "
            "Every storyboard defines 1 to 3 reusable assets (main subject or character, optionally "
            "location and style frame), each fully describing its appearance once; scenes list the "
            "asset_ids they show and their visual_prompt covers only action, framing and camera. "
            "Preserve unchanged asset ids and descriptions; change an asset only when its look "
            "should change. "
            "Use 3 to 5 scenes totalling 6 to 30 seconds, each at most 8 seconds, 24 fps, "
            "instrumental music, and supported aspect ratios. "
            "Use the supplied project_id and brand_version. Default to settings. For "
            "storyboard-only requests set storyboard_only. "
            "Use generate_scene with an existing scene id for production requests; approval"
            " is performed by the human through cards. "
            "Use edit_composition and instruction for timeline, sound, or duration edits "
            "after a composition exists. "
            "Never approve, export, invent artifact ids, or call providers. All execution "
            "goes through application commands." + grounding
            if chatting
            else "Edit only the provided typed timeline according to the instruction. "
            "Preserve artifact ids and "
            "Preserve clip settings. Return a valid Composition. Never approve it or replace original media."
            if editing
            else (BACKEND_ROOT / "skills/product_launch/director.md").read_text() + grounding
        ),
        output_schema=DirectorConversation
        if chatting
        else DirectorComposition
        if editing
        else DirectorStoryboard,
        output_key="storyboard",
        tools=[] if chatting else [get_brand_dna],
        generate_content_config=types.GenerateContentConfig(temperature=0.4, max_output_tokens=4096),
    )
    app = App(
        name="vibeshorts", root_agent=director, resumability_config=ResumabilityConfig(is_resumable=True)
    )
    runner = Runner(app=app, session_service=sessions)
    async for event in runner.run_async(
        user_id=payload["uid"],
        session_id=session_id,
        new_message=types.Content(role="user", parts=parts),
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
            if (
                chatting
                and storyboard.storyboard
                and (
                    storyboard.storyboard.project_id != payload["project_id"]
                    or storyboard.storyboard.brand_version != payload["brand_version"]
                )
            ):
                raise ValueError("Director changed trusted context")
            if (
                not editing
                and not chatting
                and (
                    storyboard.project_id != payload["project_id"]
                    or storyboard.brand_version != payload["brand_version"]
                )
            ):
                raise ValueError("Director changed trusted context")
            print(storyboard.model_dump_json())
            await runner.close()
            return
    await runner.close()
    raise RuntimeError("Director produced no typed plan")


if __name__ == "__main__":
    asyncio.run(main())
