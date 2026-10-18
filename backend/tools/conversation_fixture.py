"""Deterministic dialogue for fixtures; live dialogue uses the ADK director."""

import re

from tools.contracts.studio import CreativePreferences, DirectorTurn, MusicInput, Scene, Storyboard


def fixture_turn(request, project, brand_version):
    text = request.instruction
    lower = text.lower()
    context = request.context
    story = context.get("storyboard")
    scene_match = re.search(r"scene\s*[- ]?([1-5])", lower)
    if re.search(r"\b(status|progress|how is|what can|help)\b", lower):
        return DirectorTurn(
            action="status",
            text=(
                f"Your video is at the {context.get('stage', 'idea')} stage. "
                "Review the latest card to continue."
            ),
        )
    if (
        context.get("composition")
        and re.search(r"\b(shorten|trim|mute|replace|title|background|accent|landscape|portrait)\b", lower)
        and not scene_match
    ):
        return DirectorTurn(
            action="edit_composition",
            text="I’ll update the combined video and keep your original version.",
            instruction=text[:2000],
        )
    if story:
        plan = Storyboard.model_validate(story)
        # Mirror conversational style choices for offline acceptance flows.
        chosen = next(
            (v for v in ("cinematic", "cartoon", "collage", "3d") if re.search(r"\b" + v + r"\b", lower)),
            None,
        )
        if chosen or "slow motion" in lower:
            plan.creative_preferences = CreativePreferences(
                vibe=chosen or (plan.creative_preferences.vibe if plan.creative_preferences else None),
                motion="slow_motion" if "slow motion" in lower else "real_time",
            )
        if scene_match:
            sid = "scene-" + scene_match[1]
            scene = next((s for s in plan.scenes if s.id == sid), None)
            if not scene:
                return DirectorTurn(
                    action="clarify",
                    text="That scene is not in this storyboard. Which scene would you like to change?",
                )
            if re.search(r"\b(create|generate|continue)\b", lower) and not re.search(
                r"\b(change|update|revise|regenerate)\b", lower
            ):
                return DirectorTurn(
                    action="generate_scene",
                    scene_id=sid,
                    text="Review the storyboard or current scene card to continue.",
                )
            copy = re.search(r'(?:copy|text|caption).*?["\'](.+?)["\']', text, re.I)
            if copy:
                scene.exact_copy = [copy[1][:120]]
            else:
                scene.visual_prompt = text
            return DirectorTurn(
                action="storyboard",
                storyboard=plan,
                text="I’ve updated that scene in the storyboard. Review the new plan before continuing.",
            )
        if re.search(r"\b(change|update|revise|storyboard|style|motion)\b", lower):
            for scene in plan.scenes:
                scene.visual_prompt = text + ". " + scene.objective
            return DirectorTurn(action="storyboard", storyboard=plan, text="Here’s the revised storyboard.")
        return DirectorTurn(
            action="clarify",
            text="Would you like to revise a scene, change the storyboard, or continue production?",
        )
    settings = context["settings"]
    duration_match = re.search(r"(\d+)\s*(?:second|sec|s)\b", lower)
    duration = float(duration_match[1]) if duration_match else settings["duration_seconds"]
    if not 6 <= duration <= 30:
        return DirectorTurn(
            action="clarify", text="I can make videos from 6 to 30 seconds. What duration would you like?"
        )
    count = max(3, min(5, int((duration + 7) // 8)))
    labels = ["Opening", "The main idea", "The ending", "A closer look", "Final thought"]
    plan = Storyboard(
        project_id=project,
        brand_version=brand_version,
        skill_version="explainer@1.0",
        duration_seconds=duration,
        aspect_ratio=settings["aspect_ratio"],
        scenes=[
            Scene(
                id=f"scene-{i + 1}",
                objective=labels[i],
                exact_copy=[labels[i]],
                editorial_duration_seconds=duration / count,
                visual_prompt=text + ". " + labels[i],
                reference_artifact_ids=request.reference_artifact_ids,
            )
            for i in range(count)
        ],
        music=MusicInput(prompt="Instrumental music matching the story, no vocals"),
    )
    only = bool(re.search(r"\b(only|just)\b.*\bstoryboard\b", lower))
    return DirectorTurn(
        action="storyboard",
        storyboard=plan,
        storyboard_only=only,
        text="Here’s your storyboard. We’ll stop here until you choose to create the scenes."
        if only
        else "Let’s start with a storyboard. You can change anything before we create the first scene.",
    )
