# VibeShorts 🎬⚡

**VibeShorts** is an agentic, brand-adaptive short-form video generation platform inspired by Higgsfield Supercomputer. It orchestrates creative ideation, hyperframe visual anchoring, camera-controlled video synthesis, brand-themed dynamic motion graphics, and audio stem scoring on an end-to-end Google stack.

---

## 1. System Architecture Overview

```
                          ┌────────────────────────────────────────┐
                          │   Next.js 15 Client (A2UI / SSE)       │
                          │  - CopilotKit / Assistant-UI Agent Log │
                          │  - Remotion Live Preview & Tldraw Canvas│
                          └───────────────────▲────────────────────┘
                                              │ SSE / WebSocket
                                              ▼
                          ┌────────────────────────────────────────┐
                          │   FastAPI Gateway (Cloud Run)          │
                          │  - Firebase Auth / Tenant Middleware   │
                          │  - Google ADK Workflow Runner          │
                          └─────────────┬──────────────┬───────────┘
                                        │              │
                   Dispatches Tasks     │              │ Session / Rate Tokens
                                        ▼              ▼
     ┌─────────────────────────────────────┐        ┌────────────────────────────┐
     │ Google ADK Multi-Agent Orchestrator │        │ Redis (Memorystore)        │
     │ - Director Agent (Script & Beats)   │        │ - Session State & Cache    │
     │ - Hyperframe Agent (Nano Banana)    │        │ - Multi-Tenant Queues      │
     │ - Motion Designer (Remotion Specs)  │        └────────────────────────────┘
     │ - Sound Engineer (Lyria BGM)        │
     └──────────────────┬──────────────────┘
                        │ Model Context Protocol (MCP)
                        ▼
     ┌───────────────────────────────────────────────────────────────────────────┐
     │                           VibeShorts MCP Server                           │
     ├─────────────────────────────────┬─────────────────────────────────────────┤
     │ [Nano Banana] Hyperframe Anchor │ [Google Veo 3] Video Motion Synthesis   │
     ├─────────────────────────────────┼─────────────────────────────────────────┤
     │ [Google Lyria] Score & Stems    │ [Gemini Omni] QC, Voiceover & Branding │
     ├─────────────────────────────────┼─────────────────────────────────────────┤
     │ [Remotion / Skia] Motion Vector │ [Cloud Storage] Multi-Tenant Media Sink │
     └─────────────────────────────────┴─────────────────────────────────────────┘
```

---

## 2. Technology Stack

| Layer | Component | Choice | Justification |
| :--- | :--- | :--- | :--- |
| **Agent Framework** | Orchestrator & State | **Google ADK (`google-adk`)** | Native multi-agent delegation, built-in session isolation, first-class MCP integration, and native multi-modal artifact tracking. |
| **Frontend** | UI & Live Workbench | **Next.js 15 (React 19)** + **CopilotKit** + **Remotion** | Real-time tool execution cards, thought traces, canvas-based keyframe viewer (Tldraw), and client-side motion graphic previews. |
| **Backend** | API & Server Streaming | **Python FastAPI** (asyncio) | High-concurrency SSE streaming, non-blocking agent task pipelines, and dynamic MCP routing. |
| **Visual Anchoring** | Keyframes / Storyboard | **Google Nano Banana** | Rapid, deterministic generation of consistent start/end hyperframe pairs locked to brand guidelines. |
| **Video Engine** | Motion Interpolation | **Google Veo 3** | High-fidelity video generation utilizing hyperframe anchor pairs and explicit camera motion vectors. |
| **Audio Engine** | Audio & Scoring | **Google Lyria** | Context-aware, beat-matched background music and ambient soundscape synthesis. |
| **Visual Reasoning** | Scripting & Quality Control | **Gemini Omni** | Multi-modal script analysis, scene breakdown, brand compliance validation, and visual consistency checks. |
| **Database** | Metadata & Tenancy | **Cloud SQL (PostgreSQL 16)** + `pgvector` | Row-Level Security (RLS) for tenant isolation; vector search for brand DNA assets. |
| **Storage & Jobs** | Assets & Queues | **Google Cloud Storage (GCS)** + **Cloud Tasks** | Path-partitioned tenant buckets with presigned URLs; quota-guarded asynchronous rendering pipelines. |
| **Infrastructure** | Container Compute | **Cloud Run** + **Google Kubernetes Engine (GKE)** | Autoscaling serverless API gateway; dedicated GKE CPU/GPU workers for headless Remotion/FFmpeg rendering. |

---

## 3. Core Components

### 3.1. Google ADK Agent Hierarchy
* **Director Agent:** Deconstructs the marketing brief into pacing beats, scenes, visual prompts, and camera movements.
* **Continuity & Hyperframe Agent:** Generates starting and ending visual keyframes using Nano Banana, checking face, lighting, and style consistency against the brand vector store.
* **Motion Graphics Agent:** Synthesizes parametric Remotion configurations (typography, colors, lower-thirds, animations) derived directly from the brand kit.
* **Sound Engineer Agent:** Generates voiceover timing and prompts Lyria for beat-matched audio cues.

### 3.2. Multi-Tenancy & Security
* **Authentication:** Firebase Authentication / Google Cloud Identity Platform issuing JWTs containing tenant and role claims (`tenant_id`, `role: creator|admin`).
* **Database Isolation:** PostgreSQL Row-Level Security enforces tenant separation:
  ```sql
  ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
  CREATE POLICY tenant_isolation_policy ON projects
    USING (tenant_id = current_setting('app.current_tenant', true));
  ```
* **Storage Isolation:** GCS paths structured as:
  ```
  gs://vibeshorts-artifacts/{tenant_id}/{project_id}/{asset_type}/{asset_id}.{ext}
  ```

---

## 4. VibeShorts MCP Server (Model Context Protocol)

The MCP server exposes foundational generation tools to both internal Google ADK agents and external agents (Cursor, Claude Desktop, autonomous agents).

### Exposed Tool Registry

```json
[
  {
    "name": "generate_hyperframes",
    "description": "Produces starting and ending visual anchor frames for a shot using Google Nano Banana.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "scene_prompt": { "type": "string" },
        "brand_id": { "type": "string" },
        "aspect_ratio": { "type": "string", "enum": ["9:16", "16:9", "1:1"] },
        "camera_direction": { "type": "string" }
      },
      "required": ["scene_prompt", "brand_id"]
    }
  },
  {
    "name": "render_veo_clip",
    "description": "Synthesizes smooth video transitions between hyperframe anchors using Google Veo 3.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "start_frame_url": { "type": "string" },
        "end_frame_url": { "type": "string" },
        "motion_prompt": { "type": "string" },
        "duration_seconds": { "type": "number", "maximum": 60 }
      },
      "required": ["start_frame_url", "motion_prompt"]
    }
  },
  {
    "name": "synthesize_lyria_audio",
    "description": "Generates audio tracks and stems aligned with scene tempo and mood using Google Lyria.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "genre_and_mood": { "type": "string" },
        "bpm": { "type": "integer" },
        "duration": { "type": "number" }
      },
      "required": ["genre_and_mood", "duration"]
    }
  },
  {
    "name": "render_motion_overlay",
    "description": "Compiles brand-themed motion graphics (captions, typography, transitions) via headless Remotion.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "template_id": { "type": "string" },
        "brand_tokens": { "type": "object" },
        "captions": { "type": "array" }
      },
      "required": ["template_id", "brand_tokens"]
    }
  }
]
```

---

## 5. Streaming Protocol & Event Schema

FastAPI streams ADK agent steps and artifacts to the frontend using Server-Sent Events (SSE) over `/api/projects/{id}/generate`:

| Event Type | Payload Attributes | Purpose |
| :--- | :--- | :--- |
| `thought` | `{ agent, step, thought }` | Renders the live internal reasoning trace in the UI. |
| `tool_start` | `{ tool, parameters, timestamp }` | Shows the active working task badge (e.g., *Rendering Veo 3 Shot 2*). |
| `artifact` | `{ artifact_id, type, url, mime_type }` | Live updates the UI workbench with intermediate images, raw clips, or audio stems. |
| `completion` | `{ project_id, export_url, duration }` | Signals job completion and renders the final composite video player. |

---

## 6. Deployment Topology on GCP

* **Ingress & Security:** Google Cloud Armor (WAF/DDoS) $\rightarrow$ Global External HTTP(S) Load Balancer.
* **Web Tier:** Next.js 15 client hosted on Google Cloud Run (SSR + WebSocket/SSE proxy).
* **API & Orchestrator:** FastAPI + Google ADK hosted on Google Cloud Run with concurrency set to 80 requests/container.
* **Async Workers:** Cloud Tasks triggers distributed rendering workers on GKE equipped with high-CPU/GPU nodes for headless Remotion and FFmpeg stitching.
* **State & Caching:** Google Cloud SQL (PostgreSQL 16) with Private Service Connect + Memorystore for Redis.