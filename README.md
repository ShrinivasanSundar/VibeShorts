# VibeShorts

AI-native video editor with **Antigravity SDK**, **GenMedia MCP**, and **GCP Vertex AI**.

This repo **is** the product. There is no extra `vibeshorts/vibeshorts` wrapper. Shared engine code lives at the root; `cli/` is only the command-line interface; `webui/` is reserved for a later browser UI.

```
VibeShorts/                 # this git repo
├── src/vibeshorts/         # Python package (import vibeshorts) — agents, Vertex, MCP, pipeline
├── config/                 # shared pipeline, styles, MCP templates
├── skills/                 # shared Antigravity skills
├── cli/                    # command-line interface only
└── webui/                  # future browser studio / Web UI
```

`src/vibeshorts/` is the Python import name (`import vibeshorts`), not a second product folder. After clone you get `VibeShorts/cli`, not `VibeShorts/vibeshorts/cli`.

## Architecture

```
vibeshorts create (CLI)  ──┐
                           ├──►  shared pipeline
vibeshorts studio / webui ─┘         │
                                     ▼
                          Showrunner (Antigravity SDK)
                                     │
                          MCP + Vertex (Gemini, Veo, Lyria, STT)
                                     ▼
                          Director → Trim Refiner → Editor → Reviewer
                                     ▼
                          timeline.json + final.mp4
```

## Quick start

### Prerequisites

- Python 3.11+
- FFmpeg on PATH
- Google Cloud project with Vertex AI enabled
- `gcloud auth application-default login`
- Optional: GenMedia MCP binaries (`mcp-veo-go`, `mcp-lyria-go`, etc.)
- Optional: Node.js 22+ for Hyperframes (`npx hyperframes`)

### Install

```bash
pip install -e ".[preprocess]"
```

### Initialize a project

```bash
vibeshorts init ./my-project
cd my-project
# Edit vibeshorts.yaml — set GCP project and GenMedia bucket
```

### Create a video

```bash
vibeshorts create \
  --footage ./footage \
  --brief ./brief.yaml \
  --output ./renders/final.mp4 \
  --style ./config/styles/dtc-testimonial.yaml
```

### Other commands

```bash
vibeshorts config validate
vibeshorts config mcp
vibeshorts render --engine hyperframes
vibeshorts studio --port 8787
vibeshorts chat "Add B-roll of a coffee shop at 0:10"
```

See [cli/README.md](cli/README.md) for CLI-only details.

## Configuration

Copy `config/vibeshorts.yaml.template` to a project root as `vibeshorts.yaml`:

| Variable | Description |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | GCP project ID |
| `GENMEDIA_BUCKET` | `gs://bucket` for Veo/Lyria output |
| `GOOGLE_CLOUD_LOCATION` | Vertex region (default `us-central1`) |

## Shared library vs CLI

| Location | Responsibility |
|---|---|
| `src/vibeshorts/` | Models, agents, Vertex clients, MCP, pipeline, render tools, Studio server |
| `config/`, `skills/` | Templates shared by CLI and future Web UI |
| `cli/` | Typer commands (`init`, `create`, `render`, `studio`, `chat`, `config`) |
| `webui/` | Future browser UI; not implemented yet |

## Integrations

### Antigravity SDK

The Showrunner agent uses `google-antigravity` with Vertex, GenMedia MCP, skills from `skills/`, and multimodal video review.

### GenMedia MCP

Configured via `.agents/mcp_config.json`:
- **veo** — B-roll generation
- **lyria** — background music
- **chirp3-hd** — text-to-speech
- **avtool** — FFmpeg media operations
- **gemini** — multimodal understanding
- **imagen** — reference image generation

### GCP Vertex AI

Direct Python clients in `src/vibeshorts/integrations/vertex/`:
- `GeminiClient` — structured EditPlan, trim probes, review
- `VeoClient` — B-roll via `veo-3.1-generate-001`
- `LyriaClient` — background music
- `SpeechClient` — voice-driven editing via Cloud STT

## Generated project layout

```
my-project/
├── footage/
├── brief.yaml
├── timeline.json
├── footage_index.json
├── vibeshorts.yaml
├── .agents/
│   ├── mcp_config.json
│   └── skills/
├── composition/
└── renders/
```

## Background

Feasibility notes and engine research remain in:
- [AGENTIC_VIDEO_EDITOR_ANALYSIS.md](AGENTIC_VIDEO_EDITOR_ANALYSIS.md)
- [HYPERFRAMES_ANALYSIS.md](HYPERFRAMES_ANALYSIS.md)
