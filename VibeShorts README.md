# VibeShorts

> **AI-native creative studio for generating, editing, and composing short-form video using autonomous agents.**

VibeShorts transforms a natural-language creative brief into production-ready short-form videos using **Google ADK, Nano Banana, Veo, Gemini/Omni, Lyria, Hyperframes, and VibeShorts MCP**.

The goal is not to build another traditional video editor. VibeShorts is an **agentic creative workspace** where users describe what they want, watch the agent work in real time, review generated artifacts, and iteratively refine the final video.

---

## ✨ Vision

```text
Creative Intent
      ↓
     Agent
      ↓
 Creative Skills
      ↓
  VibeShorts MCP
      ↓
Google Media Models
      ↓
  Hyperframes
      ↓
Composition / Rendering
      ↓
 Final Video
```

Example:

> "Create a futuristic 15-second product launch video for my AI startup using our brand style."

VibeShorts can:

1. Understand the creative brief
2. Analyze the brand
3. Develop a concept
4. Create a storyboard
5. Generate keyframes
6. Generate video scenes
7. Generate music
8. Create motion graphics
9. Compose the scenes
10. Validate the result
11. Render the final video

---

# 🏗️ Architecture

```text
                              USER
                                │
                                ▼
                    ┌──────────────────────┐
                    │      Next.js         │
                    │       React          │
                    │                      │
                    │ • Canvas             │
                    │ • Timeline           │
                    │ • Asset Browser      │
                    │ • Agent Activity     │
                    │ • Artifact Viewer    │
                    └──────────┬───────────┘
                               │
                    CopilotKit + AG-UI
                               │
                               ▼
                    ┌──────────────────────┐
                    │       FastAPI        │
                    │    API / Gateway     │
                    └──────────┬───────────┘
                               │
                         Pub/Sub / Jobs
                               │
                               ▼
                    ┌──────────────────────┐
                    │      Google ADK      │
                    │    Agent Runtime     │
                    └──────────┬───────────┘
                               │
                    ┌──────────┴───────────┐
                    │                      │
                    ▼                      ▼
             VibeShorts Skills       VibeShorts MCP
                    │                      │
                    └──────────┬───────────┘
                               │
              ┌────────────────┼─────────────────┐
              │                │                 │
              ▼                ▼                 ▼
         Nano Banana          Veo             Lyria
              │                │                 │
              └────────────────┼─────────────────┘
                               │
                         Hyperframes
                               │
                    ┌──────────┴───────────┐
                    │                      │
                 Preview                Render
                    │                      │
              WebGL/Canvas          Cloud Run Jobs
                                           │
                                     FFmpeg / GPU
                                           │
                                           ▼
                                      Cloud Storage
```

---

# 🧠 Agent Architecture

VibeShorts uses **Google ADK** as the production agent framework.

Antigravity can be used as the development environment/agentic coding tool, but the VibeShorts production runtime is based on ADK.

## Multi-Agent Architecture

```text
                    Creative Director
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
      Research         Storyboard          Brand
       Agent             Agent             Agent
          │                │                │
          └────────────────┼────────────────┘
                           │
                    Production Agent
                           │
             ┌─────────────┼─────────────┐
             │             │             │
             ▼             ▼             ▼
          Image          Video          Music
          Agent          Agent          Agent
             │             │             │
             └─────────────┼─────────────┘
                           ▼
                    Motion Agent
                           │
                           ▼
                       QA Agent
                           │
                           ▼
                    Final Hyperframe
```

Agents should be specialized rather than implementing one large monolithic agent.

---

# 🎨 VibeShorts Skills

Skills describe **how creative work should be performed**.

Examples:

```text
skills/
├── brand-analysis/
├── product-launch/
├── social-ad/
├── cinematic-short/
├── ugc-video/
├── storytelling/
├── storyboard/
├── motion-graphics/
├── kinetic-typography/
├── music-direction/
├── video-localization/
└── video-quality/
```

A Skill can define:

```yaml
name: product_launch
version: 1.0

inputs:
  - product
  - brand
  - audience
  - duration
  - aspect_ratio

workflow:
  - analyze_brand
  - create_concept
  - create_script
  - create_storyboard
  - generate_keyframes
  - generate_video
  - generate_music
  - create_motion_graphics
  - compose
  - quality_check
  - render
```

Skills should be **model-agnostic**.

They should request capabilities rather than directly depending on a specific model.

---

# 🧬 Brand DNA

Every organization/project can have a persistent Brand DNA.

```json
{
  "colors": {
    "primary": "#2864FF",
    "secondary": "#7C3AED"
  },

  "typography": {
    "heading": "Inter",
    "body": "Inter"
  },

  "visual_style": [
    "futuristic",
    "minimal",
    "high contrast"
  ],

  "motion_style": [
    "fast",
    "cinematic",
    "elastic"
  ],

  "music_style": [
    "electronic",
    "energetic"
  ]
}
```

Skills automatically use Brand DNA when creating content.

This enables:

> **Create content that consistently looks, sounds, and moves like the brand.**

---

# ⚡ Hyperframes

Hyperframes are the core creative representation of VibeShorts.

A Hyperframe is a declarative representation of a visual scene.

```json
{
  "id": "scene_03",
  "duration": 4.5,

  "layers": [
    {
      "type": "video",
      "asset": "veo_scene_03"
    },
    {
      "type": "text",
      "content": "Create without limits",
      "animation": "kinetic_reveal"
    },
    {
      "type": "particle",
      "preset": "neon"
    }
  ],

  "camera": {
    "motion": "slow_push",
    "zoom": 1.08
  },

  "audio": {
    "music": "lyria_track_01"
  }
}
```

A complete video is composed of Hyperframes:

```text
Project
 └── Timeline
      ├── Hyperframe 01
      ├── Hyperframe 02
      ├── Hyperframe 03
      └── Hyperframe 04
```

### Why Hyperframes?

They allow agents to manipulate creative intent without directly manipulating rendering code.

Examples:

```text
"Make Scene 3 more cinematic"
        ↓
Modify Hyperframe

"Make the animation faster"
        ↓
Modify Hyperframe

"Apply our brand style"
        ↓
Modify Hyperframe

"Make the typography more dramatic"
        ↓
Modify Hyperframe
```

The Hyperframe format should remain independent of the underlying renderer.

---

# 🤖 VibeShorts MCP

VibeShorts exposes its creative capabilities through an MCP server.

This allows VibeShorts capabilities to be used by:

- VibeShorts agents
- Gemini agents
- Claude
- ChatGPT
- Cursor
- Antigravity
- Custom agents
- Other AI applications

## MCP Categories

### Creative

```text
create_video
create_short
create_ad
create_storyboard
create_scene
```

### Media

```text
generate_image
generate_video
generate_music
analyze_image
analyze_video
```

### Editing

```text
trim_video
split_video
compose_video
add_captions
add_transition
resize_video
localize_video
```

### Brand

```text
create_brand
analyze_brand
get_brand_dna
apply_brand_style
validate_brand_consistency
```

### Hyperframes

```text
create_hyperframe
update_hyperframe
get_hyperframe
compose_hyperframes
render_hyperframe
```

### Project

```text
list_assets
get_asset
search_project
get_project_context
```

Long-running operations return a `job_id` rather than blocking the request.

```json
{
  "job_id": "job_123",
  "status": "queued"
}
```

---

# 🖥️ Frontend

## Stack

```text
Next.js
React
TypeScript
Tailwind CSS
shadcn/ui
CopilotKit
AG-UI
Zustand
TanStack Query
Remotion Player / custom renderer
```

The frontend is a custom VibeShorts application.

CopilotKit is used primarily for the **agent interaction layer**, not as the complete application UI.

---

# 🔄 AG-UI

AG-UI provides the agent ↔ frontend communication layer.

It streams:

```text
Agent lifecycle
Messages
Tool calls
Progress
State updates
Artifacts
Human approvals
Custom events
```

Example:

```text
✓ Analyze brand
✓ Create concept
✓ Create storyboard
✓ Generate Scene 1
● Generate Scene 2
○ Generate Scene 3
○ Render
```

The UI should expose **agent activity**, not private chain-of-thought.

Example:

> Generating Scene 2 with Veo

rather than exposing internal reasoning.

---

# 🧩 Generative UI

Agents can produce interactive UI artifacts.

Examples:

```text
Storyboard
 ├── Scene 1
 ├── Scene 2
 ├── Scene 3
 └── Scene 4

[Approve] [Modify] [Regenerate]
```

Other agent-generated interfaces:

- image selection
- video selection
- storyboard approval
- brand configuration
- generation settings
- creative alternatives
- artifact previews
- human approval checkpoints

---

# 📦 Artifact System

Everything produced by an agent is an Artifact.

```typescript
type Artifact = {
  id: string
  projectId: string
  runId: string

  type:
    | "text"
    | "image"
    | "video"
    | "audio"
    | "code"
    | "json"
    | "timeline"
    | "hyperframe"
    | "storyboard"

  title: string

  status:
    | "pending"
    | "generating"
    | "ready"
    | "failed"

  storageUri?: string

  metadata: Record<string, unknown>

  createdAt: Timestamp
}
```

The frontend contains an `ArtifactRenderer` capable of rendering each artifact type.

---

# ☁️ Google Cloud Architecture

## Core Services

| Requirement | Google Cloud |
|---|---|
| API | Cloud Run |
| Agent workers | Cloud Run |
| Database | Firestore |
| Object storage | Cloud Storage |
| Queue | Pub/Sub |
| Delayed jobs | Cloud Tasks |
| Heavy rendering | Cloud Run Jobs |
| GPU rendering | Cloud Run GPU |
| Authentication | Identity Platform |
| Secrets | Secret Manager |
| Container registry | Artifact Registry |
| CI/CD | Cloud Build |
| Observability | Cloud Logging / Trace |
| CDN | Cloud CDN |

---

# 🔐 Authentication & Multi-Tenancy

VibeShorts is multi-tenant by design.

```text
Organization
│
├── Members
│
├── Brands
│
├── Projects
│
├── Assets
│
└── Agent Runs
```

Every request is scoped by:

```text
tenant_id
workspace_id
project_id
user_id
```

Authentication:

```text
Google Identity Platform
        ↓
JWT
        ↓
FastAPI
        ↓
Authorization
```

Media files are stored in Cloud Storage.

Firestore contains metadata and state.

---

# ⚙️ Asynchronous Execution

Long-running AI operations must never block FastAPI.

```text
POST /projects/{id}/runs
            │
            ▼
       Create Run
            │
            ▼
         Pub/Sub
            │
            ▼
       ADK Worker
            │
            ├── Nano Banana
            ├── Veo
            ├── Lyria
            └── MCP
            │
            ▼
        Artifact
            │
            ▼
       Firestore/GCS
            │
            ▼
       AG-UI / Frontend
```

This architecture allows multiple users to run jobs concurrently.

---

# 📡 Realtime Agent State

Agent execution state is persisted.

Example:

```json
{
  "run_id": "run_123",
  "status": "running",

  "current_step": {
    "type": "video_generation",
    "message": "Generating Scene 3",
    "progress": 63
  },

  "steps": [
    {
      "type": "brand_analysis",
      "status": "completed"
    },
    {
      "type": "storyboard",
      "status": "completed"
    },
    {
      "type": "video_generation",
      "status": "running"
    }
  ]
}
```

Firestore realtime updates can initially power the UI.

A dedicated WebSocket/realtime gateway can be introduced later at larger scale.

---

# 🎬 Media Pipeline

```text
Creative Brief
      ↓
Brand Analysis
      ↓
Storyboard
      ↓
Keyframes
      │
      ├── Nano Banana
      │
      ▼
Video Generation
      │
      └── Veo
      │
      ▼
Video Transformation
      │
      └── Gemini / Omni
      │
      ▼
Music
      │
      └── Lyria
      │
      ▼
Hyperframes
      │
      ▼
Motion Graphics
      │
      ▼
Composition
      │
      ▼
Render
      │
      ▼
Final Video
```

---

# 🖼️ Media Providers

The application should use provider abstractions.

```python
class VideoProvider:
    async def generate(
        self,
        prompt: str,
        references: list,
        duration: float,
        aspect_ratio: str
    ):
        ...
```

The Skill should not directly depend on:

```text
veo-3.x
```

Instead:

```text
VideoProvider
      ↓
Veo implementation
```

This keeps the architecture flexible as Google's models evolve.

---

# 🎞️ Rendering

Hyperframes are renderer-independent.

Initial architecture:

```text
Hyperframe
     ↓
VibeShorts Renderer
     ↓
Preview
```

For final rendering:

```text
Hyperframe
     ↓
Render Engine
     ↓
FFmpeg / GPU
     ↓
Cloud Storage
```

A renderer such as Remotion can be used during the initial implementation, but it should remain an implementation detail rather than the core VibeShorts data model.

Future renderers can include:

```text
WebGL
Canvas
GPU renderer
FFmpeg
Remotion
Native video renderer
```

---

# 🗂️ Suggested Repository

```text
vibeshorts/
│
├── apps/
│   ├── web/
│   │   ├── Next.js
│   │   ├── CopilotKit
│   │   ├── AG-UI
│   │   ├── canvas/
│   │   ├── timeline/
│   │   ├── artifacts/
│   │   └── agent/
│   │
│   └── api/
│       ├── FastAPI
│       ├── authentication/
│       ├── projects/
│       ├── assets/
│       ├── artifacts/
│       ├── runs/
│       └── billing/
│
├── agents/
│   ├── creative_director/
│   ├── storyboard/
│   ├── brand/
│   ├── image/
│   ├── video/
│   ├── music/
│   ├── motion/
│   └── qa/
│
├── skills/
│   ├── product_launch/
│   ├── social_ad/
│   ├── cinematic/
│   ├── ugc/
│   ├── storyboard/
│   └── motion_graphics/
│
├── mcp/
│   └── vibeshorts_mcp/
│
├── hyperframe/
│   ├── schema/
│   ├── parser/
│   ├── validation/
│   ├── animation/
│   └── renderer/
│
├── providers/
│   ├── nano_banana/
│   ├── veo/
│   ├── omni/
│   └── lyria/
│
├── workers/
│   ├── agent_worker/
│   ├── generation_worker/
│   └── render_worker/
│
├── infrastructure/
│   ├── terraform/
│   ├── cloud-run/
│   ├── pubsub/
│   └── firestore/
│
└── docs/
```

---

# 🚀 MVP

The first version should focus on one excellent workflow rather than dozens of features.

## MVP workflow

```text
Prompt
 ↓
Brand
 ↓
Storyboard
 ↓
3–5 Scenes
 ↓
Nano Banana keyframes
 ↓
Veo video
 ↓
Lyria music
 ↓
Hyperframe composition
 ↓
Final short
```

## MVP features

- Google authentication
- Multi-tenant organizations
- Project management
- Brand DNA
- Natural-language creative brief
- ADK Creative Director
- VibeShorts Skills
- Nano Banana image generation
- Veo video generation
- Lyria music generation
- Hyperframes
- Agent activity UI
- AG-UI
- CopilotKit
- Artifact system
- Video preview
- Final rendering
- Cloud Storage
- Basic usage/credit tracking

---

# 🛣️ Roadmap

## Phase 1 — Agentic Video Generation

```text
Prompt → Storyboard → Scenes → Video
```

## Phase 2 — AI Video Editor

```text
AI-generated timeline
+
Hyperframe editing
+
Natural-language editing
```

## Phase 3 — Brand Intelligence

```text
Brand DNA
+
Brand-aware Skills
+
Consistency validation
```

## Phase 4 — Creative Platform

```text
Reusable Skills
Templates
Characters
Assets
Localization
Batch generation
```

## Phase 5 — VibeShorts MCP Platform

Allow external agents to use VibeShorts:

```text
Claude
Gemini
ChatGPT
Cursor
Antigravity
Custom Agents
        ↓
VibeShorts MCP
        ↓
Creative Infrastructure
```

---

# 🎯 Core Design Principles

### 1. Agent-first

Users describe outcomes rather than manually operating every tool.

### 2. Hyperframe-first

Creative output is represented as structured, editable data.

### 3. Skills over workflows

Skills should adapt dynamically instead of forcing rigid pipelines.

### 4. MCP-first capabilities

Creative capabilities should be usable by VibeShorts and external agents.

### 5. Async by default

AI generation and rendering must run as asynchronous jobs.

### 6. Observable agents

Users should always understand what the agent is doing.

### 7. Human-in-the-loop

Users can approve, modify, regenerate, or interrupt agent workflows.

### 8. Brand consistency

Every creative operation should be able to incorporate Brand DNA.

### 9. Provider abstraction

Skills should not be tightly coupled to individual models.

### 10. Multi-tenant from day one

Tenant isolation, authorization, usage tracking, and project boundaries must be part of the initial architecture.

---

# 🔑 Technology Summary

```text
Frontend
    Next.js
    React
    TypeScript
    CopilotKit
    AG-UI
    Tailwind
    shadcn/ui
    Zustand

Backend
    Python
    FastAPI
    Google ADK

Agent
    Google ADK
    VibeShorts Skills
    VibeShorts MCP

Creative AI
    Nano Banana
    Veo
    Gemini / Omni
    Lyria

Creative Representation
    Hyperframes

Infrastructure
    GCP
    Cloud Run
    Cloud Run Jobs
    Firestore
    Cloud Storage
    Pub/Sub
    Cloud Tasks
    Identity Platform

Rendering
    Hyperframe Renderer
    FFmpeg
    GPU
```

---

## VibeShorts in one sentence

> **VibeShorts is an agentic, brand-aware creative studio where AI agents turn natural-language ideas into editable Hyperframes, cinematic short-form videos, and motion graphics using Google's generative AI stack.**