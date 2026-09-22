---
name: genmedia-video-editor
description: Expert in FFmpeg composition, overlays, kinetic captions, and GIF generation for VibeShorts.
---

# GenMedia Video Editor Skill

Use FFmpeg and avtool MCP for deterministic video operations.

## Capabilities

- Cut and trim clips with frame-accurate boundaries
- Concatenate segments with crossfades
- Burn ASS kinetic captions (TikTok/Reels style)
- Mix background music with auto-ducking
- Export vertical 9:16 (1080x1920) H.264

## Tools

Prefer MCP `avtool` for media operations when available.
Fall back to local FFmpeg via `vibeshorts.tools.ffmpeg`.

## Caption style

- Font: Montserrat
- Highlight color: #4ACFFF
- Word-level karaoke from Whisper timestamps
