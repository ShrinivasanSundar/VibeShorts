# VibeShorts

> **AI-native creative studio for generating, editing, and composing short-form video using autonomous agents.**

VibeShorts turns a natural-language brief into an editable HeyGen HyperFrames composition and a rendered short. Build VibeShorts MCP and the common tool layer first; then one Google ADK Creative Director uses those tools to produce Nano Banana keyframes, Veo video plates, and Lyria music.

**Status:** MCP/API, Firebase identity and OAuth, durable media jobs, a Next.js Studio with timeline editing, approval gates and fixture video export are implemented. Start with [Studio setup and workflow](docs/STUDIO.md), [environment setup](docs/SETUP.md), and [compatibility](docs/COMPATIBILITY.md), and [verification record](docs/VALIDATION.md). The complete fixture workflow is verified locally; live providers and cloud deployment require credentials and target-environment validation. The roadmap and remaining extensions are distinguished in the Studio guide.

**Documentation verified:** 3 October 2026. Model availability, launch stage, region, SDK compatibility, and pricing must be rechecked when dependencies are pinned and before deployment.

## Contents

- [Architecture](#architecture)
- [First video](#first-video)
- [Agent and session persistence](#agent-and-session-persistence)
- [Skills and storyboard](#skills-and-storyboard)
- [Brand DNA](#brand-dna)
- [VibeShorts MCP and common tools](#vibeshorts-mcp-and-common-tools)
- [Run, step, job, and artifact contracts](#run-step-job-and-artifact-contracts)
- [Durable execution and recovery](#durable-execution-and-recovery)
- [Firebase authentication and access gating](#firebase-authentication-and-access-gating)
- [Google provider integrations](#google-provider-integrations)
- [Media pipeline](#media-pipeline)
- [HyperFrames, editing, and rendering](#hyperframes-editing-and-rendering)
- [Approvals and quality checks](#approvals-and-quality-checks)
- [Budgets and concurrency](#budgets-and-concurrency)
- [Frontend, realtime, and observability](#frontend-realtime-and-observability)
- [Google Cloud and repository](#google-cloud-and-repository)
- [MVP and roadmap](#mvp-and-roadmap)
- [Acceptance scenarios](#acceptance-scenarios)
- [Design principles and references](#design-principles-and-references)

---

## Architecture

```text
Browser → Firebase Authentication → verified app requests → FastAPI
External agent → MCP OAuth backed by Firebase sign-in → /mcp
ADK director → native bindings OR MCP
                         │
                         ▼
              Common application commands
              project authorization · schemas · budgets
                         │
                         ▼
       Firestore: runs, jobs, approvals, ledger, outbox
                         │
               Outbox dispatcher → Pub/Sub
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
       Director invocations     Job execution
       creative decisions       provider submission / polling
              │                     │
              └── child jobs ───────┤
                                    ▼
                     Nano Banana · Veo · Lyria
                    Vertex AI OR Gemini Developer API
                                    │
                                    ▼
                     Immutable artifacts in Cloud Storage
                                    │
                                    ▼
                      Packaged HyperFrames composition
                         │                     │
                         ▼                     ▼
                 Isolated preview       Draft render / checks
                         │
                   Preview approval
                         │
                         ▼
                  Isolated final render
                  Cloud Run job → mp4
```

The director is the only **creative** orchestrator. Application code owns durable execution, dependency scheduling, cancellation, authorization, budget enforcement, and recovery. Job execution is infrastructure, not another planning agent. Skills describe creative policy.

Both native and MCP bindings submit the same application commands. Dedicated internal handlers execute accepted jobs. A worker may use either binding, but a public tool must not mean “enqueue” for one caller and “execute the provider inline” for another. The director never calls `create_video` to invoke itself.

---

## First video

Example brief:

> Create a futuristic 15-second product launch video for my startup using our brand style.

1. Verify the signed-in user and project access; snapshot the brief, skill version, brand version, and spend cap.
2. The director produces a typed storyboard. Validate it and request approval of that exact storyboard revision.
3. On approval, create dependent production jobs. Each scene gets a keyframe, then a video plate. Independent scenes may overlap; continuity introduces explicit dependencies.
4. Generate instrumental music alongside the video jobs.
5. Inspect and prepare the media: dimensions, trim points, frame rate, audio, and any continuity frames.
6. Produce an immutable HyperFrames package using prepared media, exact brand assets, type, and seekable motion.
7. Run structural checks and a draft render. Show the accepted package in the isolated preview.
8. Request approval of that exact composition revision; then enqueue final export.
9. Validate the resulting mp4, store it in project-owned Cloud Storage, settle costs, and mark the run `succeeded`.

A completed package may be edited in Studio or by the director. Each save creates a revision, and final export requires approval of the new revision.

---

## Agent and session persistence

### ADK responsibilities

Use Python Google ADK with one `LlmAgent` Creative Director. Its `App` holds agent configuration and resumability; a `Runner` executes invocations against persistent session and artifact services. Record `app_name`, `session_id`, `invocation_id`, and pending tool-call identifiers on the corresponding run/step.

Enable `ResumabilityConfig(is_resumable=True)` on the app. Resume the existing invocation where the pinned ADK version supports it; correlate intermediate/final tool results with the original call. This is not an exactly-once execution guarantee, and custom agent code needs its own resume support. See [ADK resumability](https://adk.dev/runtime/resume/).

Use short function tools for reads and submissions. Long-running tool bindings start external jobs and let the application deliver later results. They do not keep the agent process alive throughout generation or human approval. This separation follows [ADK function and long-running tool guidance](https://adk.dev/tools-custom/function-tools/).

The native binding can wrap a submission in `LongRunningFunctionTool`. The optional MCP binding uses `McpToolset` with a restricted tool filter and Streamable HTTP connection. MCP discovery alone does not turn a queued result into an ADK deferred completion: implement a result bridge that records pending call/job associations, persists waiting state, and resumes only when the required results are durable. Integration and cleanup must be tested against the pinned SDK. See [ADK MCP tools](https://adk.dev/tools-custom/mcp-tools/).

Keep file payloads out of conversational history. Pass artifact ids, compact metadata, and selected preview references. Record the director model and prompt/policy versions; a provider retry does not rerun the director unless its creative output actually needs revision.

### Firestore-backed sessions

**VibeShorts must implement a Firestore adapter for Python ADK's `BaseSessionService`.** It is a project-owned component, not a claimed built-in Python `FirestoreSessionService`. The documented session alternatives include in-memory, SQL-backed `DatabaseSessionService`, and managed services. See [ADK session services](https://adk.dev/sessions/session/).

The adapter must implement the pinned service interface for creating, getting, listing, and deleting sessions, plus appending events and applying state deltas. Preserve event identifiers, invocation/tool-call correlation, timestamps, and state scopes. Session ownership must bind to the trusted Firebase UID and project; never accept an arbitrary client's session id without authorization.

```text
Firestore
├── projects/{project_id}/runs, steps, jobs, approvals, artifacts, events
├── projects/{project_id}/outbox
├── budgets/{budget_id}/entries
└── adk_sessions/{session_id}
    └── events/{event_id}
```

ADK session events are the conversation and invocation history. VibeShorts job records are authoritative for execution, permissions, costs, and artifacts. Do not duplicate provider truth in an ADK state blob. A persisted completion can enqueue resumption again after a crash; a result-delivery marker and invocation lease prevent concurrent delivery, while shared command idempotency protects any replayed tool call.

Serialize invocations for one session with a cross-process lease. Append events and state changes transactionally with duplicate-event protection and an expected session version. Store schema/ADK compatibility metadata, index ordered event reads, and define export, deletion, and migration behavior before upgrades. Do not put all events in one growing document.

`InMemorySessionService` is acceptable for disposable local demonstrations; it cannot pass restart recovery. Use the Firestore emulator with the project adapter for persistence and multi-worker acceptance checks. GCS-backed ADK artifact access, if used, must map to the application artifact registry rather than creating an independent unscoped media catalog.

---

## Skills and storyboard

A skill is model-agnostic creative policy interpreted by the director. Hard constraints are validated in application code, even if the director proposes skipping or repeating a creative step.

```yaml
name: product_launch
version: 1.0
policy:
  duration_seconds: 15
  aspect_ratio: "9:16"
  scene_count: [3, 5]
  shot_grammar:
    - open on the product
    - one claim per scene
    - end on the brand mark
  brand: use the snapshotted project brand bundle
```

The approved `StoryboardSpec` is a typed plan, not free-form text used as execution instructions. Its minimum contract:

```typescript
type StoryboardSpec = {
  schema_version: 1
  project_id: string
  brand_version: string
  skill_version: string
  duration_seconds: number
  aspect_ratio: "9:16" | "16:9"
  fps: number
  scenes: {
    id: string
    objective: string
    exact_copy: string[]
    editorial_duration_seconds: number
    visual_prompt: string
    reference_artifact_ids: string[]
    continuity_from_scene_id?: string
  }[]
  music: { prompt: string; instrumental: boolean }
}
```

Validate scene count, total editorial timing including overlaps, references, dependency cycles, safe type placement, and the chosen provider's supported generation settings before requesting approval. Provider source duration is planned separately from the cut duration. Persist the approved plan as an immutable storyboard artifact.

---

## Brand DNA

Each project has an immutable, versioned brand bundle. Snapshot its version at the start of a run and reference it on creative outputs.

```json
{
  "id": "brand_01",
  "version": 3,
  "colors": { "primary": "#2864FF", "secondary": "#7C3AED" },
  "fonts": {
    "heading": "art_font_heading_v1",
    "body": "art_font_body_v1"
  },
  "logo": "art_logo_v2",
  "reference_frames": ["art_reference_v1"],
  "do": ["high contrast", "short lines of type"],
  "dont": ["script faces", "stock-photo hands"],
  "caption": {
    "visual_style": ["futuristic", "minimal"],
    "motion_style": ["fast", "cinematic"],
    "music_style": ["electronic", "energetic"]
  }
}
```

Resolve artifact ids to authorized files when packaging the composition. Place exact logo and typography assets as controlled overlays where possible; do not require generated video to reproduce them precisely. A brand update affects future runs unless the user explicitly creates a revision against the new bundle. Automated consistency scoring is later work; required assets and brand colors/fonts are validated in the MVP.

---

## VibeShorts MCP and common tools

### Transport and execution boundary

MCP is the first product interface to build. Expose the official Python MCP SDK over Streamable HTTP at `/mcp`; a local stdio entry point can reuse the adapter. Pin SDK and protocol compatibility with the intended clients, using the [MCP architecture documentation](https://modelcontextprotocol.io/docs/learn/architecture). The examples below describe VibeShorts payloads, not a protocol-specific wire envelope.

Typed application contracts are the source of schemas for MCP, REST, and native ADK bindings. Adapters handle transport and verified identity; common commands handle permissions, validation, idempotency, job creation, artifacts, and budget reservations. Internal job handlers call provider adapters.

### Tool surface

| Public MCP tool | Common capability | Behavior |
|---|---|---|
| `get_brand_dna` | `brand.read` | Read one authorized bundle/version |
| `generate_image` | `image.generate` | Submit an image job |
| `generate_video` | `video.generate` | Submit a plate job; first-frame artifact required for this workflow |
| `generate_music` | `music.generate` | Submit a music job |
| `inspect_media`, `extract_frame` | `media.inspect`, `media.extract_frame` | Read media facts or submit preparation work |
| `prepare_media` | `media.prepare` | Submit validated trims, normalization, and audio treatment |
| `get_hyperframe` | `composition.read` | Read an immutable package manifest |
| `create_hyperframe`, `update_hyperframe` | `composition.write` | Submit a validated package write against an expected head |
| `render_hyperframe` | `render.enqueue` | Submit a draft or approved final export |
| `get_project_context` | `project.read` | Return a bounded project summary |
| `list_assets`, `get_asset` | `artifact.list`, `artifact.read` | Paginated authorized metadata and short-lived access URLs |
| `get_capabilities` | `provider.capabilities` | Read configured route/model capabilities |
| `get_job`, `get_run` | `job.read`, `run.read` | Read operation or workflow state |
| `cancel_job`, `cancel_run` | `job.cancel`, `run.cancel` | Request operation or workflow cancellation |
| `create_video` (phase 1) | `run.create` | Submit a brief to the director workflow |

Read calls return directly. Long media, composition, preparation, and render commands return a job handle. Publish a tool only when its application handler exists. `create_short`/`create_ad` can later be policy presets; localization, analysis, search, and brand scoring join the same layer as they ship.

### Submission and result contracts

Every project command takes `project_id`. Every mutation takes `idempotency_key`. Do not expose privileged execution context as model-controlled arguments: the adapter resolves the caller and the application supplies any trusted parent run/step identity.

```json
{
  "project_id": "proj_1",
  "idempotency_key": "scene-01-plate-request-1",
  "input": {
    "prompt": "A slow product reveal",
    "first_frame_artifact_id": "art_keyframe_01_v1",
    "source_duration_seconds": 6,
    "aspect_ratio": "9:16"
  }
}
```

```json
{
  "job_id": "job_scene_01_plate",
  "run_id": "run_123",
  "step_id": "step_scene_01_plate",
  "status": "queued",
  "artifact_ids": [],
  "poll_after_seconds": 10
}
```

`job_id` is distinct from `run_id`. Standalone generation creates a lightweight run containing one step/job. A director submission creates a child job under its existing run through the same contract.

`get_job` returns status, typed progress when available, output artifact ids, costs, and any error. `get_run` includes active steps and the current approval request. A queued result is not a completed media artifact. Clients respect polling guidance; percentages are omitted when the provider supplies none.

Return structured payloads with a declared `outputSchema` and serialize them into a text content block for compatibility. Validation/authorization and execution failures must use the pinned MCP SDK's appropriate error mechanism; tool execution failures include `isError`. Follow the [MCP tools specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).

```json
{
  "code": "PROVIDER_SUBMISSION_UNCERTAIN",
  "message": "The provider may have accepted this operation.",
  "retryable": false,
  "action": "reconcile",
  "job_id": "job_scene_01_plate"
}
```

Use stable codes for invalid input, denied access, budget exhaustion, revision conflict, safety rejection, provider unavailability, and unknown submission. REST maps authentication failure to 401, authorization failure to 403, conflicting revisions/idempotency to 409, and invalid input to 422. Error bodies never expose credentials or another project's state.

`list_assets` accepts a bounded `limit` (default 20, maximum 100), optional type/status filters, and an opaque cursor. `get_project_context` returns ids and summaries, not all media bytes, raw session events, or private reasoning. Capability responses include model/route, launch stage, location constraints, supported inputs and parameter combinations, execution style, and verification date.

### Bootstrap and approvals

Before the director workflow, the authenticated REST API must support project creation, versioned brand updates, asset import, and composition creation. Import validates MIME type, size, content, destination ownership, and upload completion before making an artifact ready. Direct upload URLs are short lived and scoped to one server-selected object.

Storyboard and preview review live in the authenticated app. `get_run` returns an approval id, exact target artifact id, and review URL; the API checks the reviewer's permission and target version. Do not allow an external model to approve a user's work implicitly.

### MCP authorization

Firebase is the user identity source. Remote MCP clients need a **VibeShorts OAuth authorization layer**, using Firebase sign-in on its authorization page and issuing resource-bound tokens for `/mcp`. This broker is a required VibeShorts component; Firebase Authentication alone does not supply an arbitrary MCP OAuth server.

Implement authorization-server discovery, protected-resource metadata, PKCE, supported client onboarding, consent scopes, and token audience validation for the selected MCP protocol. Map the token subject/grant to the Firebase UID and current project permissions. Do not accept Firebase project-audience ID tokens as generic MCP resource tokens or forward MCP tokens to Google providers. See [MCP authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization).

Local stdio development must still have an explicit identity and scope; it is not an authentication bypass. Revoking app access must revoke linked MCP grants, and sensitive commands must recheck the user's enabled/access state.

---

## Run, step, job, and artifact contracts

These are conceptual application types to implement, not SDK types.

| Record | Owns | Important relationships |
|---|---|---|
| `Run` | Brief, plan, overall status, policy snapshot, spend cap | User/project; ADK session; steps and jobs |
| `Step` | A planned dependency node | Required step ids, exact input revisions, outputs |
| `Job` | One executable operation | Run/step, attempts, lease, provider handle, reservation |
| `ProviderOperationRef` | External accepted operation identity | Route, model, location, external name, submission time |
| `ArtifactRevision` | Published immutable result/manifest | Parent revision, full input edges, owning job, content hash |
| `Approval` | Human decision on one revision | Target, reviewer UID, decision, timestamp |
| `LedgerEntry` | Reservation or settlement | Job, shared budget, usage, rate snapshot |

### Run and job state

Run states: `queued`, `running`, `waiting_for_jobs`, `needs_approval`, `needs_reconciliation`, `succeeded`, `failed`, `cancelled`.

Job states: `queued`, `claimed`, `submitting`, `waiting_for_provider`, `materializing`, `succeeded`, `failed`, `submission_unknown`, `cancel_requested`, `cancelled`. Synchronous providers skip `waiting_for_provider`. Claim leases protect a bounded execution segment, not the entire provider lifetime.

A cancel request blocks new work promptly. Already accepted provider work may complete and incur cost. Only use a provider cancellation method if documented and supported by that route. Maintain operational records and reconcile costs even after the user-facing run is cancelled.

```json
{
  "run_id": "run_123",
  "project_id": "proj_1",
  "user_id": "firebase_uid_1",
  "status": "waiting_for_jobs",
  "version": 8,
  "brand_version": "brand_01@3",
  "storyboard_artifact_id": "art_storyboard_v1",
  "adk": {
    "app_name": "vibeshorts",
    "session_id": "session_123",
    "invocation_id": "invocation_123"
  },
  "active_steps": [
    {
      "step_id": "step_scene_02_plate",
      "job_id": "job_scene_02_plate",
      "status": "waiting_for_provider",
      "message": "Generating Scene 2 with Veo"
    },
    {
      "step_id": "step_music",
      "job_id": "job_music",
      "status": "claimed",
      "message": "Generating instrumental music"
    }
  ],
  "pending_approval_id": null
}
```

Keep run summaries compact. Store detailed jobs, attempts, events, and ledger entries separately. Dependency edges can live on step records; complete input edges live on artifact revisions.

### Artifact revisions

```typescript
type ArtifactRevision = {
  id: string
  project_id: string
  run_id: string
  job_id: string
  parent_id?: string
  input_artifact_ids: string[]
  type: "image" | "video" | "audio" | "hyperframe" | "storyboard" | "text"
  title: string
  storage_uri: string
  content_sha256: string
  brand_version?: string
  provider?: { route: string; model: string; location?: string }
  prompt_version?: string
  seed?: number
  media?: {
    duration_seconds?: number
    width?: number
    height?: number
    fps?: number
    audio_present?: boolean
  }
  created_at: string
}
```

Create an artifact revision only after its object/package is durably stored and verified. Pending generation belongs to the job. Keep availability/deletion and whether a revision is current/stale in lifecycle records; a superseded revision may still be reusable and downloadable by authorized users.

`parent_id` describes ancestry. `input_artifact_ids` describes dependency. Regenerating one plate invalidates all derived artifacts/steps reading that revision, transitively, including continuity frames. Unrelated scenes remain valid. Never infer all dependencies from a single parent pointer.

---

## Durable execution and recovery

### Submission and dispatch

```text
Authenticated command
    ↓
Validate inputs and project permissions
    ↓
Firestore transaction
    ├── idempotency mapping + canonical input hash
    ├── run / step / job
    ├── budget reservation
    └── outbox item
    ↓
Return durable ids immediately
    ↓
Dispatcher publishes outbox item → Pub/Sub
    ↓
Short worker segment claims job → internal handler
    ↓
Persist result / provider reference / next_poll_at
    ↓
Publish dependency wake-up or director resume through outbox
```

Scope idempotency by project, command, and key. Repeating the same canonical input returns existing ids; reusing the key with different input is a conflict. Do not derive client idempotency from a new server-generated run id.

The dispatcher marks an outbox item sent only after publish succeeds. Crashing after publish can duplicate messages; consumers must tolerate that. Pub/Sub push to Cloud Run is the default for short execution segments. A successful response acknowledges the persisted transition; jobs and leases, not a message connection, own work. Exactly-once delivery is not available for push subscriptions and cannot guarantee one external side effect. See [Pub/Sub delivery semantics](https://docs.cloud.google.com/pubsub/docs/exactly-once-delivery).

### Claims, polling, and resumption

Claims atomically record lease owner, expiry, and a fencing generation. Only the current claim may commit transitions; heartbeats extend an active bounded segment. Release ownership while awaiting a human or a provider. Input revision/generation checks additionally protect project-head publication.

A scheduled reconciler, invoked through authenticated Cloud Scheduler once per minute, republishes stranded outbox entries, wakes due provider polls, detects expired claims, and finds unprocessed completions. Poll handlers use persisted backoff and `next_poll_at`; they do not sleep for minutes inside a request. They return immediately if another handler already owns the job. Expired pre-submission claims can be reclaimed; expired `submitting` claims without a saved handle become `submission_unknown`, and known accepted operations resume polling/materialization rather than submission.

Use provider webhooks only if supported and authenticated; polling remains the specified baseline. Queue/poll concurrency obeys project and provider limits. Cloud Run render jobs execute the heavyweight render, with their execution ids recorded on application jobs.

Only dispatch a step when its dependencies are satisfied and its exact inputs are current. Once required jobs complete, enqueue a leased director invocation with correlated final tool results. Independent completions cannot launch simultaneous invocations on the same ADK session.

### Paid submission recovery

Before a provider call, persist `submitting`, input hash, attempt identity, and reservation. Persist the returned provider handle before scheduling polls. Use an external idempotency facility only where its guarantees are documented; do not invent one from a local seed.

If a process dies after sending a request but before saving the handle, the provider may already be generating. Mark the job `submission_unknown` and the live run `needs_reconciliation`. Recover through known handles or documented lookup/idempotency support. If recovery is impossible, require a recorded reconciliation decision before another paid submission; never automatically claim that the original operation cost nothing.

Apply the same rule to synchronous generation interrupted after the request was sent. Retain uncertain reservations. A provider failure before acceptance may be retried; safety rejection and unsupported input must return a typed failure without blind creative retries.

Upload/materialize into a job-specific candidate location; verify content and publish the artifact id transactionally. A rejected lease or stale input can leave an orphan candidate object; a cleanup process may remove unreferenced candidates after retention checks. Late results never overwrite a current revision or bypass approval.

---

## Firebase authentication and access gating

### App and API gate

Use **Firebase Authentication**, initially Google sign-in, for web identity. The public landing/sign-in page may be accessible anonymously; project pages, studio launch, data reads, job submissions, approvals, and artifact URL issuance require a signed-in, enabled user with app access.

```text
Google sign-in through Firebase Web SDK
    ↓
Firebase ID token
    ↓
Authorization: Bearer <ID token> → FastAPI
    ↓
Firebase Admin verification → trusted Firebase UID
    ↓
Enabled user + app access + project role + action permission
    ↓
Common application command
```

Enable the Google provider and approved sign-in domains in Firebase configuration. Use the Firebase Web SDK's authentication state to gate UI loading and obtain/refresh tokens; UI gating is only presentation. Every protected backend route must verify identity independently. See [Firebase Google sign-in](https://firebase.google.com/docs/auth/web/google-signin).

Verify tokens using Firebase Admin, including issuer, expected project audience, expiry, and signature. Derive `user_id` from the verified `uid`, never a request body. Missing/invalid credentials return 401. Authenticated users lacking app/project/action access receive 403. See [Firebase ID-token verification](https://firebase.google.com/docs/auth/admin/verify-id-tokens).

Illustrative verification boundary; initialize Firebase Admin with the deployment's trusted project configuration. The API must handle validation exceptions without exposing token contents:

```python
from firebase_admin import auth

def verified_uid(id_token: str) -> str:
    claims = auth.verify_id_token(id_token, check_revoked=True)
    return claims["uid"]
```

Check revocation and disabled-user state on protected requests. Store a server-controlled user access record and project ownership/membership; only privileged server code can change access or roles. Default project creator is its owner. New Firebase sign-ins may enter the app after server provisioning, but get no access to existing projects. Anonymous sign-in is not enabled for this workflow.

Use an application `access_enabled` flag to immediately gate both requests and browser read rules. Administrative revocation disables that access, revokes Firebase refresh tokens and linked MCP grants, and requests cancellation of affected work. Firebase revocation checking has an additional server check; avoid caching authorization decisions across consequential operations. See [Firebase session management](https://firebase.google.com/docs/auth/admin/manage-sessions).

### Browser data and media access

The browser may subscribe directly to a safe project/run summary projection in Firestore. Rules must check `request.auth.uid`, enabled app access, and project membership/ownership. Default deny. Client writes to runs, job state, budgets, approvals, ADK sessions, and provider handles are denied; changes go through authenticated APIs.

Server Firestore SDKs bypass Security Rules. Workload IAM and common application authorization must therefore protect server reads/writes too. See [Firestore Security Rules conditions](https://firebase.google.com/docs/firestore/security/rules-conditions).

Cloud Storage buckets stay private. The API verifies access before issuing a short-lived signed download/upload URL for one object. Download grants expire after five minutes by default; revoking membership prevents new URLs but cannot revoke an already-issued bearer URL immediately. Use authenticated delivery rather than signed URLs if immediate read revocation is required. Render sandboxes receive only their materialized package, not broad storage credentials.

CORS allows only configured app origins for browser API requests; provider keys and Admin credentials remain server-side. App Check can later help reduce abusive client traffic, but is not a replacement for authentication, role checks, or quotas.

### Background execution and cloud IAM

Do not persist Firebase ID/refresh tokens on runs or in queue messages. Record the initiating UID, project, accepted action, approved artifact ids, authorization revision, grant reference if applicable, and budget. This trusted context is generated by the server.

Before each consequential step, recheck enabled-user/app-access and current project/action permission. An expired browser ID token alone does not cancel accepted work; disabled/revoked app access or removed membership stops new steps and triggers cancellation/reconciliation policy. External work already accepted may still bill.

Cloud Run uses least-privilege workload service accounts and Application Default Credentials for Google APIs. This infrastructure identity is separate from the Firebase user's application permissions. It does not authorize arbitrary client-supplied object paths. Restrict internal dispatcher, reconciler, and worker ingress to authenticated service identities. See [Cloud Run service identity](https://docs.cloud.google.com/run/docs/securing/service-identity).

---

## Google provider integrations

### Two explicit API routes

Use the Google Gen AI SDK where its selected capability is supported. It provides clients for Gemini Developer API and Vertex AI, but model names, credentials, endpoint behavior, and feature availability differ. A route-specific adapter may use a documented REST endpoint when necessary, notably Vertex Lyria 2. See [SDK documentation](https://ai.google.dev/gemini-api/docs/libraries).

Cloud Run defaults to Vertex AI: configure a Cloud project, supported location, enabled API, quota, and workload IAM. The Developer API is an explicit alternative using a server-held API key. Each accepted job snapshots route, model, API version, location when applicable, and capability-profile version; never switch those settings automatically on a retry.

Illustrative SDK client setup; this is not a runnable repository module or a credential bootstrap script:

```python
import os
from google import genai

vertex_client = genai.Client(
    vertexai=True,
    project=os.environ["GOOGLE_CLOUD_PROJECT"],
    location=os.environ["GOOGLE_CLOUD_LOCATION"],
)

developer_client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"],
)
```

Use workload credentials in production and local ADC for Vertex development. Do not put service-account private keys in the browser or repo. Store Developer API keys in Secret Manager. Firebase app configuration is not a provider credential. See [Cloud ADC setup](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/start/gcp-auth).

### Baseline capabilities, verified 3 October 2026

These are baseline examples requested for this design, not a promise of permanent availability or equivalence. Newer models do not silently replace accepted jobs. Check launch stage and combinations against the selected model's page. A global image endpoint and a region-bound video endpoint can coexist through separate adapter configuration.

| Route / capability | Baseline model / stage | Inputs, references, and location | Output / execution |
|---|---|---|---|
| Vertex image | `gemini-2.5-flash-image` / GA baseline | Text and images; model-specific location availability | Image bytes/parts from content generation; synchronous provider call inside an application job |
| Developer image | `gemini-2.5-flash-image` / non-preview legacy baseline | Text and images; Developer API availability, not a Vertex location parameter | Image parts; persist accepted image bytes |
| Vertex video | `veo-3.1-generate-001` / GA | Prompt, initial/final frames, supported asset references; documented `us-central1` baseline | MP4, native audio, 24 fps; long-running operation; GCS output or returned bytes |
| Developer video | `veo-3.1-generate-preview` / preview | Prompt, initial/final frames, up to three references; eligibility varies by feature/region | Long-running operation; downloadable video; copy into project storage |
| Vertex music | `lyria-002` / GA baseline | Text prompt; current model page lists `global`; no assumed image input | Instrumental audio up to 32.8 seconds, WAV, 48 kHz; `predict` returns encoded audio directly |
| Developer music | `lyria-3-clip-preview` / preview | Text/image interaction; Developer API availability | 30-second MP3, 44.1 kHz stereo; interaction response contains audio; explicitly request instrumental |

Sources for image rows: [Vertex image model](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/2-5-flash-image), [Vertex image generation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/image-generation), and [Developer image generation](https://ai.google.dev/gemini-api/docs/image-generation). The Developer guide treats this Nano Banana baseline as legacy; model upgrade is an explicit configuration/capability change.

Sources for video rows: [Vertex Veo model](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/veo/3-1-generate), [Vertex first/last-frame generation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/generate-videos-from-first-and-last-frames), and [Developer Veo](https://ai.google.dev/gemini-api/docs/veo).

Sources for music rows: [Vertex Lyria model](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/lyria/lyria-002), [Vertex music generation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/music/generate-music), and [Developer music generation](https://ai.google.dev/gemini-api/docs/music-generation). Use the current model availability/profile rather than copying location settings from older examples. An instrumental request is subject to output review; do not assume every music route guarantees no vocals.

For the Veo baselines, generation lengths include 4, 6, and 8 seconds, with 9:16/16:9 output and model-dependent resolutions. Vertex reference-image generation requires 8 seconds. Developer reference/extension and high-resolution combinations have additional duration restrictions. Validate a complete combination of mode, references, duration, audio, and resolution; do not flatten it into independent boolean flags. Exact MIME/size limits and person/safety policies belong in the capability profile.

Developer Veo currently retains generated videos for two days; materialize output promptly, before marking the job successful. Vertex output to GCS must also be copied or registered in a server-selected project namespace with ownership/content verification. Model seeds are useful recorded inputs, not guarantees of exact reproduction.

### Provider interface and output lifecycle

Application tools always return durable jobs for generation, even when the upstream API is synchronous. Internal providers expose their real execution style:

```text
Veo adapter: submit → persist operation ref → scheduled poll → materialize
Image adapter: generate → inspect response → materialize
Vertex Lyria adapter: predict → decode audio → materialize
Developer Lyria adapter: interaction → retrieve audio → materialize
```

The provider adapter normalizes completed output metadata and typed failures, not all APIs into an invented start/poll shape. Persist provider operation/error details internally; public results expose authorized artifact ids and useful error categories.

Reject unsupported parameter combinations before reserving/submitting paid work where feasible. Handle missing output, filtered output, MIME mismatch, quota exhaustion, and temporary transport errors separately. Poll failures with a known operation handle retry retrieval, not generation. Blocking synchronous SDK calls must run in a bounded job executor rather than blocking the ADK event loop.

The model identifier stays configurable in the adapter but is recorded on the job and artifact. Keep optional Veo features such as extension and reference modes behind documented capability profiles; they are not required for the first short.

---

## Media pipeline

### Timing and continuity

Store `source_duration_seconds` separately from editorial `in_seconds`/`out_seconds`. Trim source plates rather than asking Veo for arbitrary cut durations.

Example: a 15-second, three-scene film at 24 fps:

| Scene | Generated plate | Editorial selection | Timeline |
|---|---|---|---|
| Product reveal | 6 seconds | 0–5 seconds | 0–5 seconds |
| Benefit | 6 seconds | 0–5 seconds | 5–10 seconds |
| Brand/CTA | 6 seconds | 0–5 seconds | 10–15 seconds |

This example uses straight cuts, 18 generated video seconds, and 15 final seconds. Overlapping transitions require corresponding timeline arithmetic. Music may be generated as a 30-second track, selected to 15 seconds, then faded and normalized.

For a continuous cut, the next scene depends on the **last displayed frame** of the preceding trimmed plate, not automatically the raw source's final frame. `extract_frame` produces an immutable anchor artifact with the source revision and frame index. Use that anchor as the next initial frame; a generated end anchor may constrain the previous shot where supported. Independent cuts use their own keyframes and may execute concurrently.

### Preparation

`media.inspect` records duration, decoded dimensions, frame rate, stream information, and MIME. `media.prepare` owns crop/scale, safe trim points, common frame rate, codec compatibility, audio normalization, and derivative creation. FFmpeg may implement preparation; final composition rendering remains HyperFrames.

Default first output profile: 9:16, 720×1280, 24 fps, H.264 MP4 with AAC stereo audio. Package stable media derivatives and supported image formats. Normalize differing provider rates and sample rates explicitly; preserve original sources.

Mute Veo plate audio by default and use the reviewed instrumental Lyria bed. Retaining native sound, adding voiceover, or ducking music requires explicit scene/audio policy and a new composition revision. Store each preparation choice so the director and Studio operate on the same source/timing facts.

---

## HyperFrames, editing, and rendering

### Immutable composition packages

HeyGen HyperFrames composition HTML is the editable scene/timeline. Timing uses `data-*` attributes; video plates, text, motion, and audio live in the composition. Preview and export reference the same immutable package.

```text
package/
├── index.html
├── manifest.json
├── compositions/
│   ├── scene-01.html
│   ├── scene-02.html
│   └── scene-03.html
└── assets/
    ├── scene-01-prepared.mp4
    ├── scene-02-prepared.mp4
    ├── music-prepared.wav
    └── brand/                    pinned fonts and logo
```

```json
{
  "schema_version": 1,
  "artifact_id": "art_composition_v2",
  "parent_id": "art_composition_v1",
  "entrypoint": "index.html",
  "input_artifact_ids": ["art_plate_01_v1", "art_music_v1", "art_logo_v2"],
  "output_profile": {
    "width": 720,
    "height": 1280,
    "fps": 24,
    "duration_seconds": 15
  },
  "files": [
    {
      "path": "index.html",
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  ],
  "runtime_lock_artifact_id": "art_runtime_lock_v1"
}
```

The manifest is abbreviated: a real package lists every file/hash and input revision. The runtime lock identifies tested HyperFrames, browser, animation dependencies, and render-container digest. No floating versions or expiring asset URLs inside the package.

Use frame-based seeking, seeded randomness where relevant, fixed output settings, and no wall-clock or render-time network dependency. Same HTML alone does not guarantee parity; inspect representative frames from the exact packaged revision. See [HyperFrames determinism](https://hyperframes.heygen.com/concepts/frame-adapters).

### Editing and publication

Studio and the director edit candidate files for a specific base revision. Both submit package writes through common `composition.write` with an expected project head. Validate and publish a new immutable artifact, then atomically compare-and-swap the current head. Never edit already-published files in place.

A conflicting write returns `REVISION_CONFLICT`; it does not silently merge or overwrite. A later plate completion checks its input revisions and generation fence before changing the head. Retain a stale output for history/reuse without presenting it as current. Dependency invalidation determines which work to repeat.

Saving a composition creates a new preview approval target. Approval of revision 1 cannot authorize final rendering of revision 2.

### Preview and render isolation

Treat composition HTML/JavaScript as executable user/agent content. Serve previews on a separate origin inside a sandboxed iframe, without app cookies or arbitrary parent-page access. Media playback/scrubbing messages use a validated, narrow channel.

Run rendering in an isolated browser/container workspace containing only its materialized package and approved bundled dependencies. Deny arbitrary filesystem paths, external network access, cloud metadata access, and browser access to provider/Admin credentials. The host execution wrapper transfers the package and result using narrow permissions; it does not expose those credentials to composition code.

Bound memory, CPU, duration, output size, and supported runtime features. Validate relative paths and dependency references at package acceptance. Tests must demonstrate isolation, not merely assume that Cloud Run deployment is a sandbox.

```text
Validated package → draft render / checks → exact preview revision
                                            ↓
                                      human approval
                                            ↓
                              final hyperframes render
                                            ↓
                                MP4 stream/frame checks
                                            ↓
                                  private Cloud Storage
```

A draft render is validation work; it does not imply approval for final export. Draft costs are disclosed and budgeted. Record Cloud Run execution ids and output package digests. Final rendering loads the approved package even if the project head advances later, but does not promote an older export as current.

---

## Approvals and quality checks

### Two version-bound gates

1. **Storyboard approval:** authorizes the production plan and its snapshotted spend allowance before paid media generation.
2. **Preview approval:** authorizes final export of the exact reviewed composition package.

Store approval id, type, target revision, reviewer UID, decision, timestamp, and accepted budget/version. The approval API verifies current permissions and expected target, commits the decision plus resume outbox entry transactionally, and rejects duplicate/conflicting decisions appropriately. Editing the relevant target invalidates its approval.

No worker remains resident while awaiting a person. A review URL is an authenticated route, not a bearer approval secret. MCP clients poll/run-read through these pauses. Automatic export is not the MVP default.

### Checks and repair ownership

| Check | Owner / repair |
|---|---|
| Invalid storyboard or provider settings | Director revises plan before approval |
| Missing/rejected keyframe or plate | Owning generation job; human decision for safety/uncertain submission |
| Wrong media duration, dimensions, streams | Preparation job; retain the source |
| Missing assets, invalid timing, failed `hyperframes check` | Composition step |
| Warped product, unreadable type, off-brand framing | Keyframe/draft visual review; specific creative revision |
| Wrong or clipping audio | Preparation/mix revision; new preview |
| Blank frames or final MP4 stream failure | Render/package diagnosis; retry only the responsible operation |

Structural checks confirm the package is playable; they do not prove creative quality. Review product identity, copy, branding, safe zones, shot pacing, and audio against the brief. Include exact logo/type overlays where possible.

Default to one automatic creative revision per failing scene; a further attempt requires the user's decision and remaining budget. A still-image motion treatment is a proposed fallback that the user accepts, not an invisible downgrade. Safety rejection is not bypassed by an automatic prompt rewrite. After any creative repair, validate and review the resulting revision again.

---

## Budgets and concurrency

The ledger, not the UI's cost counter, owns spending. Record estimated, reserved, settled, and uncertain amounts per job, plus provider usage and the rate snapshot used for estimates/settlement. Include images, source video seconds, music, director tokens, preparation, draft/final rendering, and retries. Providers may not return final billing cost directly.

Reserve atomically against both the run allowance and its shared project/account budget before paid submission. Parallel scenes cannot independently pass the same available-balance check. A caller-supplied cap can lower the server allowance, never raise it.

Settle once per accepted operation when usable usage/cost information is available; reconcile with billing later if necessary. Keep uncertain liabilities reserved. Cancellation stops new reservations but does not erase costs already incurred. An idempotent replay returns the same reservation/job. Reservation limits govern approved estimates; provider billing can differ, so use conservative estimates and expose discrepancies rather than promising a perfect hard limit on external charges.

Initial configurable limits: at most two concurrent video submissions per project and one active final render per project, additionally bounded by provider/project quota. Transport retries use persisted backoff and a bounded attempt/deadline policy; retrying retrieval of an accepted operation is separate from buying another generation. Exhausted budgets or retry limits produce actionable state rather than an unbounded director loop.

---

## Frontend, realtime, and observability

Use Next.js, React, TypeScript, Tailwind, shadcn/ui, Zustand, TanStack Query, Firebase Web SDK, HyperFrames player, and an authenticated Studio launch flow.

The screen contains the brief, versioned brand/artifact list, active jobs, approvals, preview, and exports. A signed-out user sees sign-in rather than protected project data. Sign-out detaches Firestore subscriptions and clears project-scoped UI/cache state.

Firestore run summaries are the UI projection. Jobs/approvals/ledger records own detailed application truth. ADK sessions own conversation events. The mutation that changes application state updates its summary version and appends a sequenced event transactionally; replay/repair can rebuild the projection. AG-UI events, if exposed, are a projection of these application events rather than a competing state store.

Show “Generating Scene 2 with Veo,” concurrent music status, and genuine approval/cancellation state. Do not display private model reasoning or invented progress percentages. Store only sanitized public errors in browser-readable summaries.

Propagate a trace id through commands, outbox, workers, provider calls, and render executions. Track queue age, expired leases, unresolved submissions, poll errors, provider latency, spend reservations versus settlement, render failures, creative acceptance, and Firebase/access denials. Include run/job/attempt/revision ids in structured logs; never log tokens or provider keys.

---

## Google Cloud and repository

| Requirement | Service / responsibility |
|---|---|
| Web/API and MCP | Next.js and FastAPI on configured hosting / Cloud Run |
| App identity gate | Firebase Authentication with Google sign-in |
| Browser read authorization | Firestore Security Rules |
| Server/job authorization | Common application policy plus workload IAM |
| Director and short job handlers | Cloud Run services |
| Draft/final render | Isolated Cloud Run job running `hyperframes render` |
| Application data and ADK adapter | Firestore |
| Media and packages | Private Cloud Storage |
| Dispatch | Pub/Sub with application idempotency |
| Reconciliation wake-up | Cloud Scheduler, one-minute authenticated sweep |
| Provider routes | Vertex AI by default; explicit Gemini Developer API option |
| Secrets | Secret Manager |
| Images / deployment | Artifact Registry and Cloud Build |
| Observability | Cloud Logging and Trace |

Choose model-specific locations rather than assuming every provider is available in one region. Configure Firebase project/authorized domains, GCS ownership, Firestore indexes/rules, internal service identity, OAuth metadata, model quota, and provider capability profiles before enabling paid jobs.

Repository structure:

```text
vibeshorts/
├── apps/
│   ├── web/                       Firebase sign-in, preview, approvals, Studio
│   └── api/                       Firebase verification, REST, OAuth identity bridge
├── mcp/vibeshorts_mcp/             transport and schemas, built first
├── tools/
│   ├── contracts/                 common typed commands/results and errors
│   ├── bindings/                  native ADK and MCP adapters
│   ├── media/
│   └── composition/
├── agents/creative_director/       ADK App and result/resume bridge
├── sessions/firestore/             project-owned BaseSessionService adapter
├── execution/                     jobs, leases, outbox, ledger, reconciliation
├── worker/                        internal provider/preparation handlers
├── providers/                     image, Veo, Lyria; explicit route adapters
├── skills/product_launch/         versioned creative policy
├── compositions/                  candidate workspaces; immutable packages in GCS
└── infrastructure/                Firebase rules, IAM, Cloud Run, queue, scheduler
```

Configure dependencies in lockfiles during implementation. Record tested ADK, Firebase Admin/Web, Google Gen AI SDK, MCP SDK/protocol, HyperFrames/browser, and adapter schema versions. Validate upgrades with emulator/recovery and provider-capability checks; examples here do not substitute for a pinned compatibility record.

---

## MVP and roadmap

### Phase 0 — MCP-first vertical slices

1. **Recoverable media operation:** Firebase gate, project/asset bootstrap, common contracts, one image MCP tool, job reads/cancel, private artifact retrieval, reservations, outbox, and worker recovery.
2. **Image-to-video:** explicit API routes, capability validation, durable Veo operation tracking, output materialization, and preparation/continuity extraction.
3. **Fixed composition:** reviewed instrumental music, immutable HyperFrames package, isolated draft/preview/final render, preview approval, and MP4 validation.

Each slice has a real external MCP client acceptance path. ADK is added after these tools work independently. Native bindings use the same commands; their transport choice remains open.

### Phase 1 — Agentic video generation

Add the single ADK director, Firestore session adapter, typed storyboard, both approval gates, tool-result resume bridge, and `create_video`. Deliver one 15-second product-launch workflow with budgeted 3–5 scenes and private exports.

### Phase 2 — Editing

Natural-language and Studio edits through immutable revisions, expected-head checks, dependency invalidation, and fresh preview approval. Regenerate only the work that reads changed inputs.

### Phase 3 — Brand intelligence

Automated consistency assessment and stronger reference handling. Versioned brand bundles and exact assets already ship in the MVP.

### Phase 4 — Creative platform

More policies, templates, shared assets, organizations, localization, and batch runs. Add specialist agents only when evaluation demonstrates a benefit. Extend MCP through the common layer as capabilities ship.

---

## Acceptance scenarios

These are required implementation checks, not claims that tests or provider calls have already run.

| Scenario | Expected behavior |
|---|---|
| Missing/expired/wrong-project Firebase token | Backend denies protected requests; no job or reservation created |
| Disabled/revoked user or removed project access | New sensitive work denied; pending work rechecks permission and enters cancellation policy |
| Browser tries to write jobs/budgets or read another project | Security Rules deny; server checks independently deny the equivalent API request |
| Forged UID, artifact path, or ADK session id | Verified identity and project ownership prevail |
| MCP token wrong audience / revoked grant | Access denied; token is not forwarded to a provider |
| Native and MCP submission parity | Same validation, permissions, durable ids, and accounting |
| Duplicate submission / changed input under same key | Existing job returned / conflict; no second reservation |
| Crash after database commit, before publish | Outbox reconciliation dispatches work |
| Duplicate dispatch / expired lease / late completion | One current transition owner; stale worker cannot publish project head |
| Crash after paid submission, before handle persistence | `submission_unknown`; retain liability and reconcile before re-purchase |
| Known Veo handle but polling failure | Retry polling the existing operation, not generation |
| Restart during approval or awaited jobs | Restore ADK session/call context; no resident process required |
| Music and independent scenes complete together | Separate jobs; consistent summary; serialized director resume |
| Parallel reservations / exhausted cap | Atomic shared budget enforcement; actionable rejection |
| Provider safety rejection or unsupported combination | Typed failure; no blind workaround or paid fallback |
| Cancel during provider/render work | Stop new steps; retain attempt/result/cost reconciliation |
| Provider download URL expires or head advances | Approved packaged assets remain renderable |
| Concurrent Studio/director edit | Expected-head conflict; user revision not overwritten |
| Scene feeds the next scene's continuity anchor | Transitive invalidation includes downstream extraction/plate |
| Edit after storyboard/preview approval | New target requires its own approval |
| Composition attempts forbidden network/file access | Preview/render isolation blocks it; resource limits terminate runaway work |
| Structurally valid but poor creative output | Specific review failure; bounded repair or explicit fallback |
| Final MP4 missing audio/wrong duration/blank frames | Export not marked ready; responsible step diagnosed |

Standalone trace: Firebase/OAuth identity → project permission → image command → reservation/job/outbox → claim → synchronous provider output → verified GCS artifact → settled job → authorized retrieval.

Full-run trace: authenticated brief → leased director → persisted storyboard → approval → child image/video/music jobs → media preparation → immutable composition → draft checks/preview → approval → final render → MP4 validation → settled `succeeded` run.

Documentation validation checks links/anchors, code fences, JSON, Python snippet syntax, state/type terminology, and these traces. Emulator/SDK integration, sandbox isolation, and paid-provider acceptance must happen during implementation.

---

## Design principles and references

1. **MCP first, common contracts:** native and MCP transports share application semantics.
2. **One creative director:** deterministic application services enforce execution rules.
3. **Firebase identity, project permissions:** sign-in does not grant access to every project.
4. **Durable by default:** leases, checkpoints, outbox, and reconciliation survive processes.
5. **Explicit uncertainty:** accepted external work is not safely repeated just because local state is incomplete.
6. **Immutable media and packages:** ancestry, dependency, and current-head state are distinct.
7. **Two human gates:** production plan and final composition approvals target exact revisions.
8. **Budget before purchase:** concurrent reservations and uncertain costs remain visible.
9. **One composition representation:** prepared media and HyperFrames files drive preview and export.
10. **Observable product state:** UI events show work and decisions, not private reasoning.

Official references are linked beside the claims they support. Start with [ADK runtime resumability](https://adk.dev/runtime/resume/), [Firebase identity verification](https://firebase.google.com/docs/auth/admin/verify-id-tokens), [Google Gen AI SDK](https://ai.google.dev/gemini-api/docs/libraries), [Vertex Veo](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/veo/3-1-generate), and [Developer Veo](https://ai.google.dev/gemini-api/docs/veo). Recheck these against the chosen model/API and dependency versions; baseline names and feature support are not timeless.

> **VibeShorts is a Firebase-gated, brand-aware creative studio where shared MCP/native tools and one director turn a brief into an approved, editable HyperFrames composition and a rendered short.**
