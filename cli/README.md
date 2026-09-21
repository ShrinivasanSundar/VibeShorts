# VibeShorts CLI

AI-native video editor CLI with **Antigravity SDK**, **GenMedia MCP**, and **GCP Vertex AI** integrations.

## Architecture

```
vibeshorts create
       │
       ▼
Showrunner Agent (Antigravity SDK)
       │
       ├── MCP: veo, lyria, chirp3-hd, avtool, gemini, imagen
       ├── Vertex: Gemini, Veo, Lyria, Speech-to-Text
       │
       ▼
Pipeline: Director → Trim Refiner → Editor → Reviewer
       │
       ▼
timeline.json + final.mp4 (FFmpeg or Hyperframes)
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
cd cli
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
  --style ../config/styles/dtc-testimonial.yaml
```

### Other commands

```bash
vibeshorts config validate          # Check GCP/MCP integration status
vibeshorts config mcp               # Generate .agents/mcp_config.json
vibeshorts render --engine hyperframes
vibeshorts studio --port 8787       # Visual timeline + agent WebSocket
vibeshorts chat "Add B-roll of a coffee shop at 0:10"
```

## Configuration

Copy `config/vibeshorts.yaml.template` to your project root as `vibeshorts.yaml`:

| Variable | Description |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | GCP project ID |
| `GENMEDIA_BUCKET` | `gs://bucket` for Veo/Lyria output |
| `GOOGLE_CLOUD_LOCATION` | Vertex region (default `us-central1`) |

## Integrations

### Antigravity SDK

The Showrunner agent uses `google-antigravity` with:
- Vertex AI backend (`vertex=True`)
- GenMedia MCP servers
- Agent skills from `cli/skills/`
- Multimodal video review

### GenMedia MCP

Configured via `.agents/mcp_config.json`:
- **veo** — B-roll generation
- **lyria** — background music
- **chirp3-hd** — text-to-speech
- **avtool** — FFmpeg media operations
- **gemini** — multimodal understanding
- **imagen** — reference image generation

### GCP Vertex AI

Direct Python clients in `integrations/vertex/`:
- `GeminiClient` — structured EditPlan, trim probes, review
- `VeoClient` — B-roll via `veo-3.1-generate-001`
- `LyriaClient` — background music
- `SpeechClient` — voice-driven editing via Cloud STT

## Project layout

```
my-project/
├── footage/              # Raw clips
├── brief.yaml            # Creative brief
├── timeline.json         # Unified timeline state
├── footage_index.json    # Preprocessed shot index
├── vibeshorts.yaml       # Config
├── .agents/
│   ├── mcp_config.json   # GenMedia MCP servers
│   └── skills/           # Agent skills
├── composition/          # Hyperframes HTML project
└── renders/              # Output videos
```
