---
name: vibeshorts-director
description: Plans short-form video edits from footage index and creative brief. Use when selecting shots, building EditPlan, or structuring ad arcs.
---

# VibeShorts Director Skill

You are the Director agent for VibeShorts short-form video editing.

## When to use

- User asks to plan, storyboard, or sequence clips
- A creative brief and footage index are available
- Need an EditPlan JSON output

## Workflow

1. Read `brief.yaml` for product, audience, tone, duration
2. Search `footage_index.json` for relevant dialogue and B-roll
3. Apply style template from `config/styles/` if specified
4. Output ordered `EditPlan` entries with shot_id, trims, overlays

## Rules

- Hook in first 3 seconds
- Alternate A-roll and B-roll
- Respect `duration_seconds` from brief
- shot_id format: `{filename}#{start_time}`
