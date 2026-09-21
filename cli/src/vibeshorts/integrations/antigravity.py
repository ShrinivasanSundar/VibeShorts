"""Antigravity SDK showrunner agent orchestration."""

from __future__ import annotations

import json
from pathlib import Path

from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.types import from_file

from vibeshorts.config import PACKAGE_ROOT, VibeShortsConfig
from vibeshorts.integrations.mcp import build_genmedia_mcp_servers, load_mcp_config
from vibeshorts.models.schemas import CreativeBrief, EditPlan, ReviewScore

SHOWRUNNER_INSTRUCTIONS = """You are the VibeShorts Showrunner Agent — the master orchestrator for
AI-native short-form video editing.

Your responsibilities:
1. Maintain the unified timeline.json project state
2. Coordinate Director, Trim Refiner, Editor, GenMedia, and Reviewer sub-agents
3. Use MCP GenMedia tools (veo, lyria, chirp3-hd, avtool, gemini) when generative media is needed
4. Use FFmpeg tools for deterministic cuts, captions, and assembly
5. Emit structured EditPlan JSON for the deterministic editor

Workflow:
- Preprocess footage into a FootageIndex (shots, transcripts, word timestamps)
- Director selects shots and produces an EditPlan from the creative brief
- Trim Refiner probes ~6s clips around trim points for frame-accurate cuts
- Editor renders via FFmpeg or Hyperframes
- Reviewer scores the output; retry with critique if below threshold

Always prefer deterministic FFmpeg edits for cuts/trims. Only invoke Veo for explicit B-roll
requests and Lyria for background music. Keep responses actionable and structured.
"""


class ShowrunnerAgent:
    """Wraps the Google Antigravity SDK for VibeShorts orchestration."""

    def __init__(self, config: VibeShortsConfig, project_dir: Path):
        self.config = config
        self.project_dir = project_dir
        self._agent_config = self._build_config()

    def _build_config(self) -> LocalAgentConfig:
        mcp_path = self.project_dir / self.config.antigravity.mcp_config_path
        mcp_servers = load_mcp_config(mcp_path)
        if not mcp_servers and self.config.integrations.enable_mcp_genmedia:
            mcp_servers = build_genmedia_mcp_servers(self.config)

        skills_paths = self.config.antigravity.skills_paths or [
            str(PACKAGE_ROOT / "skills"),
            str(self.project_dir / ".agents" / "skills"),
        ]

        return LocalAgentConfig(
            system_instructions=SHOWRUNNER_INSTRUCTIONS,
            mcp_servers=mcp_servers or None,
            skills_paths=skills_paths,
            vertex=self.config.antigravity.vertex,
            project=self.config.gcp.project or None,
            location=self.config.gcp.location,
            model=self.config.antigravity.model,
            workspaces=[str(self.project_dir)],
            response_schema=EditPlan,
        )

    async def plan_edit(self, brief: CreativeBrief, footage_index_path: Path) -> EditPlan:
        prompt = [
            "Create an EditPlan for this creative brief and footage index.",
            f"Brief: {brief.model_dump_json()}",
            f"Footage index path: {footage_index_path}",
            "Return a complete EditPlan with ordered entries, trim points, and optional music/broll prompts.",
        ]
        async with Agent(self._agent_config) as agent:
            response = await agent.chat(prompt)
            text = await response.text()
            try:
                return EditPlan.model_validate_json(text)
            except Exception:
                return EditPlan(notes=text)

    async def review_render(
        self,
        brief: CreativeBrief,
        video_path: Path,
        threshold: float,
    ) -> ReviewScore:
        review_config = LocalAgentConfig(
            system_instructions=(
                "You are the VibeShorts Reviewer. Score the rendered video 0-1 on adherence, "
                "pacing, visual_quality, watchability. Provide actionable critique."
            ),
            vertex=self.config.antigravity.vertex,
            project=self.config.gcp.project or None,
            location=self.config.gcp.location,
            model=self.config.antigravity.model,
            response_schema=ReviewScore,
        )
        prompt = [
            f"Review this video against the brief: {brief.model_dump_json()}",
            from_file(str(video_path)),
            f"Pass threshold: {threshold}",
        ]
        async with Agent(review_config) as agent:
            response = await agent.chat(prompt)
            text = await response.text()
            score = ReviewScore.model_validate_json(text)
            score.compute_overall()
            score.passed = score.overall >= threshold
            return score

    async def chat(self, message: str, attachments: list[Path] | None = None) -> str:
        prompt: list = [message]
        if attachments:
            prompt.extend(from_file(str(p)) for p in attachments)

        async with Agent(self._agent_config) as agent:
            response = await agent.chat(prompt)
            return await response.text()

    def save_session_state(self, path: Path, state: dict) -> None:
        path.write_text(json.dumps(state, indent=2))
