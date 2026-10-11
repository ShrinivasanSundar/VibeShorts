"""Deterministic fixture edit grammar; live edits use the single ADK director."""

import re

from tools.contracts.errors import AppError
from tools.contracts.studio import Composition


def fixture_edit(spec, instruction):
    value = spec.model_dump()
    text = instruction.strip()
    lower = text.lower()
    replacement = re.search(r'replace\s+["\'](.+?)["\']\s+with\s+["\'](.*?)["\']', text, re.I)
    title = re.search(r'(?:title|rename)\s+(?:to\s+)?["\'](.+?)["\']', text, re.I)
    duration = re.search(r"(?:trim|shorten|duration).*?(\d+(?:\.\d+)?)\s*(?:s|seconds)", lower)
    color = re.search(r"(background|text|accent).*?(#[0-9a-f]{6})", lower)
    if replacement:
        value["clips"] = [
            {**c, "text": c["text"].replace(replacement[1], replacement[2])} for c in value["clips"]
        ]
    elif title:
        value["title"] = title[1]
    elif "mute" in lower:
        for c in value["clips"]:
            if c["kind"] in {"video", "audio"}:
                c["volume"] = 0
    elif "landscape" in lower:
        value["aspect_ratio"] = "16:9"
    elif "portrait" in lower:
        value["aspect_ratio"] = "9:16"
    elif color:
        value[{"text": "foreground", "accent": "accent", "background": "background"}[color[1]]] = color[2]
    elif duration:
        end = float(duration[1])
        value["duration_seconds"] = end
        value["clips"] = [
            {**c, "duration": min(c["duration"], end - c["start"]), "fade_in": 0, "fade_out": 0}
            for c in value["clips"]
            if c["start"] < end
        ]
    else:
        raise AppError(
            "UNSUPPORTED_FIXTURE_EDIT",
            'Fixture edits support replace "old" with "new", mute, colors, title, aspect ratio, and trim. '
            "Configure the ADK director for general edits.",
        )
    return Composition.model_validate(value)


def invalidation(commands, project, changed):
    """Transitive immutable artifact edges; continuity anchors participate like any input."""
    from tools.commands import project_path

    artifacts = commands.repo.list(project_path(project, "artifacts"))
    affected = set(changed)
    while True:
        descendants = {a["id"] for a in artifacts if set(a["input_artifact_ids"]) & affected}
        if descendants <= affected:
            return sorted(affected)
        affected.update(descendants)
