import zlib
import urllib.request
import os

def encode64(data):
    r = ''
    mapping = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_'
    for i in range(0, len(data), 3):
        b0 = data[i]
        b1 = data[i+1] if i+1 < len(data) else 0
        b2 = data[i+2] if i+2 < len(data) else 0
        c0 = b0 >> 2
        c1 = ((b0 & 0x3) << 4) | (b1 >> 4)
        c2 = ((b1 & 0xF) << 2) | (b2 >> 6)
        c3 = b2 & 0x3F
        r += mapping[c0]
        if i + 1 < len(data):
            r += mapping[c1]
        else:
            r += mapping[c1]
            break
        if i + 2 < len(data):
            r += mapping[c2]
            r += mapping[c3]
        else:
            r += mapping[c2]
            break
    return r

def plantuml_url(puml_text, fmt='svg'):
    zlibbed = zlib.compress(puml_text.strip().encode('utf-8'), 9)
    deflated = zlibbed[2:-4]
    encoded = encode64(deflated)
    return f"https://www.plantuml.com/plantuml/{fmt}/{encoded}"

diagrams = {}

# Diagram 1: System Architecture
diagrams["arch"] = """@startuml
!theme plain
skinparam backgroundColor #FFFFFF
skinparam shadowing false
skinparam roundCorner 8
skinparam defaultFontName "Helvetica", "Arial", sans-serif
skinparam defaultFontSize 12

!define C_INGRESS #E1F5FE
!define C_AUTH #FFE0B2
!define C_APP #E8F5E9
!define C_DATA #FFF9C4
!define C_AGENT #EDE7F6
!define C_PROVIDER #FCE4EC
!define C_RENDER #E0F2F1
!define C_ALERT #FFCDD2

title VibeShorts - End-to-End System Architecture\\nClient Ingress, Invariant Enforcement, Execution Boundary, and Rendering

package "Clients & Ingress Layer" as pkg_ingress {
  actor "User / Studio Browser\\n(Next.js + React + shadcn)" as user #C_INGRESS
  component "External Agent / IDE\\n(Claude, Cursor, etc.)" as ext_agent #C_INGRESS
}

package "Authentication & Authorization Gate" as pkg_auth {
  component "Firebase Authentication\\n(Google Sign-In / ID Tokens)" as fb_auth #C_AUTH
  component "VibeShorts OAuth Broker\\n(PKCE / Scope Validation)" as mcp_oauth #C_AUTH
}

package "FastAPI Application Core" as pkg_api {
  interface "HTTP / REST API\\n(Bearer Token)" as rest_api
  interface "Streamable HTTP\\n/mcp" as mcp_endpoint
  
  component "Common Application Commands\\n- Project Authorization\\n- Strict Schema Validation\\n- Budget Reservations\\n- Idempotency Gate" as cmd_layer #C_APP
}

package "Persistence Layer (Firestore)" as pkg_db {
  database "Cloud Firestore" as firestore #C_DATA {
    folder "projects/{id}/" {
      [runs, steps, jobs] as db_jobs
      [approvals & ledger] as db_ledger
      [immutable artifacts] as db_artifacts
      [transactional outbox] as db_outbox
    }
    folder "adk_sessions/{id}" {
      [ADK Event Log & Leases] as db_adk_events
    }
  }
}

package "Durable Dispatch & Orchestration" as pkg_dispatch {
  component "Outbox Dispatcher" as dispatcher #C_APP
  queue "Google Cloud Pub/Sub\\n(Push Subscriptions)" as pubsub #C_DATA
  component "Cloud Scheduler\\n(1-min Authenticated Sweep)" as scheduler #C_ALERT
  
  component "Short-Lived Worker\\n(Cloud Run Services)" as worker #C_APP
}

package "Creative Orchestration" as pkg_agent {
  component "Google ADK Creative Director\\n(Single LlmAgent + BaseSessionService Adapter)" as adk_director #C_AGENT
  note right of adk_director
    ResumabilityConfig(is_resumable=True)
    - Interprets YAML Brand/Skill policy
    - Proposes typed StoryboardSpec
    - Emits child jobs; paused during generation
  end note
}

package "Google AI Provider Adapters" as pkg_providers {
  component "Provider Gateway\\n(Vertex AI [Default] | Gemini Dev API)" as prov_gateway #C_PROVIDER
  component "Image Adapter\\n(gemini-2.5-flash-image)" as prov_img #C_PROVIDER
  component "Video Adapter\\n(veo-3.1-generate-001)" as prov_veo #C_PROVIDER
  component "Music Adapter\\n(lyria-002)" as prov_music #C_PROVIDER
}

package "Media & Storage" as pkg_storage {
  storage "Private Cloud Storage (GCS)\\n- Normalized derivatives\\n- Immutable composition packages\\n- Signed 5-min URLs" as gcs #C_DATA
}

package "Composition & Render Engine" as pkg_render {
  component "Media Preparation\\n(FFmpeg crop/scale/audio)" as prep #C_RENDER
  component "Isolated Preview\\n(Sandboxed iframe, cross-origin)" as preview_box #C_RENDER
  component "Final Render Job\\n(Isolated Cloud Run Job\\nhyperframes render -> MP4)" as render_job #C_RENDER
}

user --> fb_auth : 1. Google Sign-In
fb_auth --> rest_api : Verified Bearer Token
ext_agent --> mcp_oauth : 1. OAuth Sign-In
mcp_oauth --> mcp_endpoint : Verified Resource Token

rest_api --> cmd_layer
mcp_endpoint --> cmd_layer

cmd_layer --> firestore : Transaction (Job + Reservation + Outbox)
cmd_layer ..> adk_director : Native / MCP Binding

db_outbox --> dispatcher : Trigger
dispatcher --> pubsub : Publish
pubsub --> worker : Push Claim

scheduler ..> firestore : Sweep expired leases & stuck outbox

worker --> adk_director : Dispatch creative step
worker --> prov_gateway : Dispatch provider job

prov_gateway --> prov_img
prov_gateway --> prov_veo
prov_gateway --> prov_music

prov_img --> gcs : Keyframe artifacts
prov_veo --> gcs : Raw video plates
prov_music --> gcs : Instrumental audio

gcs --> prep : Normalize & trim
prep --> db_artifacts : Package Manifest

db_artifacts --> preview_box : Render Preview
db_artifacts --> render_job : Final Render (on Gate 2 approval)
render_job --> gcs : Validated MP4 Export
@enduml"""

# Diagram 2: Two Gate Lifecycle
diagrams["lifecycle"] = """@startuml
!theme plain
skinparam backgroundColor #FFFFFF
skinparam shadowing false
skinparam roundCorner 6
skinparam sequenceMessageAlign center
skinparam defaultFontName "Helvetica", "Arial", sans-serif

autonumber

actor "Creator\\n(Browser)" as User #FFE0B2
participant "FastAPI\\nAPI Layer" as API #E1F5FE
participant "ADK Creative\\nDirector" as Director #EDE7F6
database "Firestore &\\nOutbox" as DB #FFF9C4
queue "Pub/Sub &\\nWorkers" as Worker #E8F5E9
participant "Providers\\n(Veo / Image / Lyria)" as Providers #FCE4EC
participant "HyperFrames\\nEngine" as HF #E0F2F1

== Phase 1: Ingestion & Storyboard Planning ==

User -> API: POST /runs (Brief + Brand Bundle + Spend Cap)
API -> DB: Commit Run [status=running], Budget Reservation, Outbox
API -> Worker: Dispatch Run to Director
Worker -> Director: Invoke with Brand DNA & Skill Policy
Director -> Director: Formulate typed StoryboardSpec (scenes, grammar, timings)
Director -> DB: Save Storyboard Artifact Revision v1
DB -> API: Update Run [status=needs_approval]
API --> User: Notify: Storyboard Review Ready

== GATE 1: Storyboard Approval ==

note over User, API #FFF8E1
  HUMAN GATE 1: STORYBOARD APPROVAL
  Validates scene breakdown, visual prompts, editorial timing,
  and confirms estimated credit/cost reservation.
end note

User -> API: POST /approvals {target: "art_storyboard_v1", decision: "approved"}
API -> DB: Commit Approval transaction + Enqueue Child Jobs [status=waiting_for_jobs]

== Phase 2: Parallel Asset Generation & Continuity ==

par Keyframe & Music Generation
  Worker -> Providers: gemini-2.5-flash-image (Scene 1 Keyframe)
  Providers --> Worker: Keyframe 1 Image
  Worker -> Providers: lyria-002 (30s Instrumental Audio Bed)
  Providers --> Worker: Master Audio WAV
end

Worker -> Providers: veo-3.1-generate-001 (Scene 1 Plate using Keyframe 1)
note right of Providers: Polling via scheduled worker\\nDuration: 4/6/8s
Providers --> Worker: Scene 1 Raw Plate MP4

Worker -> Worker: Extract last displayed frame (Scene 1 anchor)
Worker -> Providers: veo-3.1-generate-001 (Scene 2 Plate using Anchor)
Providers --> Worker: Scene 2 Raw Plate MP4

== Phase 3: Media Preparation & Composition Packaging ==

Worker -> Worker: Media Prep (FFmpeg: Crop 9:16, 24fps, Trim 0-5s, Mute Plates)
Worker -> HF: Assemble package/ (index.html, manifest.json, scene-01.html, brand assets)
HF -> DB: Publish Immutable Package Revision: art_composition_v1
HF -> HF: Run Automated Structural Checks (hyperframes check)
HF -> HF: Execute Draft Render (low-cost sanity check)
DB -> API: Update Run [status=needs_approval]
API --> User: Notify: Preview Ready on Isolated Player

== GATE 2: Composition Preview Approval ==

note over User, API #FFF8E1
  HUMAN GATE 2: PREVIEW APPROVAL
  Creator inspects timeline playback, text overlays, typography,
  brand colors, and pacing in sandboxed player.
end note

User -> API: POST /approvals {target: "art_composition_v1", decision: "approved"}
API -> DB: Commit Approval transaction + Enqueue Final Render Job

== Phase 4: Final Sandboxed Render & Export ==

Worker -> HF: Cloud Run Job: hyperframes render (art_composition_v1)
note right of HF: Isolated container:\\nNo external network,\\nFixed 720x1280 @ 24fps
HF -> HF: Frame-by-frame Seek & Composite
HF -> Worker: Final output.mp4
Worker -> Worker: Stream/Duration/Audio Verification
Worker -> DB: Settle Budget Ledger & Mark Run [status=succeeded]
API --> User: Video Ready for Download!
@enduml"""

# Diagram 3: Run State Machine
diagrams["run_state"] = """@startuml
!theme plain
skinparam backgroundColor #FFFFFF
skinparam state {
  BackgroundColor #F5F5F5
  BorderColor #424242
  RoundCorner 8
}
skinparam state<<Highlight>> {
  BackgroundColor #FFF9C4
  BorderColor #F57F17
}
skinparam state<<Danger>> {
  BackgroundColor #FFCDD2
  BorderColor #C62828
}
skinparam state<<Success>> {
  BackgroundColor #C8E6C9
  BorderColor #2E7D32
}

[*] --> queued : Brief received & authorized

queued --> running : Director claimed by worker
running --> needs_approval<<Highlight>> : Storyboard proposed by Director

needs_approval --> waiting_for_jobs : Gate 1 approved by user
needs_approval --> running : Director revisions requested
needs_approval --> cancelled<<Danger>> : Rejected / Cancelled by user

waiting_for_jobs --> waiting_for_jobs : Child jobs completing in parallel
waiting_for_jobs --> needs_reconciliation<<Danger>> : Paid provider failure / unknown state
waiting_for_jobs --> needs_approval<<Highlight>> : Composition packaged & draft verified

needs_approval --> running : Gate 2 approved (Final Render claimed)
running --> succeeded<<Success>> : MP4 validated & ledger settled

waiting_for_jobs --> cancelled<<Danger>> : Run cancelled
running --> failed<<Danger>> : Terminal error / budget exhausted
needs_reconciliation --> running : Manual reconciliation decision committed

succeeded --> [*]
failed --> [*]
cancelled --> [*]
@enduml"""

# Diagram 4: Job State Machine
diagrams["job_state"] = """@startuml
!theme plain
skinparam backgroundColor #FFFFFF
skinparam state {
  BackgroundColor #F5F5F5
  BorderColor #424242
  RoundCorner 8
}
skinparam state<<Highlight>> {
  BackgroundColor #E1F5FE
  BorderColor #0288D1
}
skinparam state<<Warning>> {
  BackgroundColor #FFE0B2
  BorderColor #E65100
}
skinparam state<<Danger>> {
  BackgroundColor #FFCDD2
  BorderColor #C62828
}
skinparam state<<Success>> {
  BackgroundColor #C8E6C9
  BorderColor #2E7D32
}

[*] --> queued : Enqueued by parent step

queued --> claimed : Worker acquires leased claim\\n(fencing token recorded)
claimed --> submitting<<Highlight>> : Budget pre-reserved;\\nCalling provider API

submitting --> waiting_for_provider<<Highlight>> : Handle saved (e.g. Veo LRO ref);\\nPeriodic backoff polling
submitting --> materializing : Synchronous API returns bytes (Gemini Flash)
submitting --> submission_unknown<<Danger>> : Crash / timeout before handle saved!

waiting_for_provider --> materializing : Provider finishes generation
waiting_for_provider --> submission_unknown<<Danger>> : Polling failure without terminal status

submission_unknown --> materializing : Cloud Scheduler reconciles via handle lookup
submission_unknown --> failed<<Danger>> : Unrecoverable; manual decision required

materializing --> succeeded<<Success>> : Content validated & artifact stored in GCS
materializing --> failed<<Danger>> : Hash mismatch / corrupted frames

claimed --> cancel_requested<<Warning>> : User / system cancel
waiting_for_provider --> cancel_requested<<Warning>> : User cancel
cancel_requested --> cancelled<<Danger>> : Provider cancelled or abandoned

succeeded --> [*]
failed --> [*]
cancelled --> [*]
@enduml"""

# Diagram 5: Crash Recovery Pattern
diagrams["crash"] = """@startuml
!theme plain
skinparam backgroundColor #FFFFFF
skinparam shadowing false
skinparam roundCorner 6
skinparam defaultFontName "Helvetica", "Arial", sans-serif

participant "FastAPI Handler" as API #E1F5FE
database "Firestore DB" as DB #FFF9C4
queue "Pub/Sub" as PS #E8F5E9
participant "Worker Process" as Worker #EDE7F6
participant "Vertex Veo API" as Veo #FCE4EC
participant "Cloud Scheduler\\n(1-min Reconciler)" as Scheduler #FFCDD2

== 1. Transactional Outbox Submission ==
API -> DB: Begin Firestore Transaction:
note right of DB
  1. Verify (project_id, idempotency_key)
  2. Reserve Budget from shared account pool
  3. Insert Job record [status=queued]
  4. Insert Outbox Item [status=pending]
end note
API -> DB: Commit Transaction
API --> API: Return job_id immediately to caller

== 2. Outbox Dispatch ==
API -> PS: Publish outbox message
PS -> Worker: Push job notification

== 3. Crash Before Handle Persistence (Uncertainty Scenario) ==
Worker -> DB: Acquire Lease Claim (expiry = +60s, fencing=gen_1)
Worker -> Veo: POST /veo/generate (Paid video request)
... WORKER CRASHES HERE (OOM / Pod Eviction) ...
note over Worker #FFCDD2
  The Veo API accepted the request and billed credit,
  but the worker died before persisting operation_ref!
end note

== 4. Scheduler Sweep & Reconciler Wake-up ==
Scheduler -> DB: Periodic 1-Minute Sweep
Scheduler -> DB: Find expired lease on Job [status=submitting]
Scheduler -> DB: Mark Job [status=submission_unknown]\\nMark Run [status=needs_reconciliation]

== 5. Reconciliation Protocol ==
Scheduler -> Veo: Query provider operations for recent idempotency key
alt Provider Handle Located
  Scheduler -> DB: Persist operation_ref, set [status=waiting_for_provider]
  Scheduler -> PS: Re-dispatch to polling queue
else Operation Unknown / Provider Unsupported
  Scheduler -> DB: Hold budget reservation as UNCERTAIN liability
  Scheduler -> DB: Request operator / user reconciliation decision
end
@enduml"""

# Diagram 6: Media DAG
diagrams["media_dag"] = """@startuml
!theme plain
skinparam backgroundColor #FFFFFF
skinparam shadowing false
skinparam roundCorner 8
skinparam defaultFontName "Helvetica", "Arial", sans-serif

!define COLOR_ASSET #E1F5FE
!define COLOR_JOB #FFF3E0
!define COLOR_PLATE #FCE4EC
!define COLOR_COMP #E0F2F1
!define COLOR_BRAND #EDE7F6

title 15-Second Product Launch: Directed Media DAG & Frame Anchoring

package "Brand Bundle (Version 3)" as pkg_brand #COLOR_BRAND {
  [Brand Colors & Fonts] as brand_style
  [Logo Overlay Asset (art_logo_v2)] as brand_logo
}

package "Scene 1: Product Reveal (0s - 5s)" as sc1 {
  [Keyframe 1 Prompt] --> [Job: Generate Image (Gemini Flash)] #COLOR_JOB
  [Job: Generate Image (Gemini Flash)] --> [Artifact: Keyframe 1 PNG] #COLOR_ASSET
  
  [Artifact: Keyframe 1 PNG] --> [Job: Veo Plate 1 (6s Source)] #COLOR_JOB
  [Job: Veo Plate 1 (6s Source)] --> [Artifact: Scene 1 Raw Plate MP4] #COLOR_PLATE
  
  [Artifact: Scene 1 Raw Plate MP4] --> [Job: Trim Plate 1 (0.0s - 5.0s)] #COLOR_JOB
  [Job: Trim Plate 1 (0.0s - 5.0s)] --> [Artifact: Scene 1 Prepared MP4] #COLOR_ASSET
  
  [Artifact: Scene 1 Prepared MP4] --> [Job: extract_frame(t = 5.0s)] #COLOR_JOB
  [Job: extract_frame(t = 5.0s)] --> [Artifact: Scene 1 Last Displayed Anchor] #COLOR_ASSET
  note bottom of [Artifact: Scene 1 Last Displayed Anchor]
    CRITICAL CONTINUITY ANCHOR:
    Last displayed editorial frame,
    NOT the raw 6th source second!
  end note
}

package "Scene 2: Core Benefit (5s - 10s)" as sc2 {
  [Artifact: Scene 1 Last Displayed Anchor] --> [Job: Veo Plate 2 (First-Frame Constrained)] #COLOR_JOB
  [Job: Veo Plate 2 (First-Frame Constrained)] --> [Artifact: Scene 2 Raw Plate MP4] #COLOR_PLATE
  
  [Artifact: Scene 2 Raw Plate MP4] --> [Job: Trim Plate 2 (0.0s - 5.0s)] #COLOR_JOB
  [Job: Trim Plate 2 (0.0s - 5.0s)] --> [Artifact: Scene 2 Prepared MP4] #COLOR_ASSET
}

package "Scene 3: Brand CTA (10s - 15s)" as sc3 {
  [Keyframe 3 Prompt] --> [Job: Generate Image (Gemini Flash 3)] #COLOR_JOB
  [Job: Generate Image (Gemini Flash 3)] --> [Artifact: Keyframe 3 PNG] #COLOR_ASSET
  
  [Artifact: Keyframe 3 PNG] --> [Job: Veo Plate 3 (6s Source)] #COLOR_JOB
  [Job: Veo Plate 3 (6s Source)] --> [Artifact: Scene 3 Raw Plate MP4] #COLOR_PLATE
  
  [Artifact: Scene 3 Raw Plate MP4] --> [Job: Trim Plate 3 (0.0s - 5.0s)] #COLOR_JOB
  [Job: Trim Plate 3 (0.0s - 5.0s)] --> [Artifact: Scene 3 Prepared MP4] #COLOR_ASSET
}

package "Audio Track" as audio {
  [Music Prompt (Electronic, 120bpm)] --> [Job: Lyria 002 (30s WAV)] #COLOR_JOB
  [Job: Lyria 002 (30s WAV)] --> [Artifact: Raw Music WAV] #COLOR_ASSET
  [Artifact: Raw Music WAV] --> [Job: Trim 15s & Audio Ducking] #COLOR_JOB
  [Job: Trim 15s & Audio Ducking] --> [Artifact: Music Prepared WAV] #COLOR_ASSET
}

package "HyperFrames Assembly" as comp #COLOR_COMP {
  [Artifact: Scene 1 Prepared MP4] --> [Job: Assemble HyperFrame Package]
  [Artifact: Scene 2 Prepared MP4] --> [Job: Assemble HyperFrame Package]
  [Artifact: Scene 3 Prepared MP4] --> [Job: Assemble HyperFrame Package]
  [Artifact: Music Prepared WAV] --> [Job: Assemble HyperFrame Package]
  brand_style --> [Job: Assemble HyperFrame Package]
  brand_logo --> [Job: Assemble HyperFrame Package]
  
  [Job: Assemble HyperFrame Package] --> [Package: art_composition_v1]
  note bottom of [Package: art_composition_v1]
    IMMUTABLE REVISION:
    - index.html
    - manifest.json (hashes)
    - runtime_lock.json
  end note
}
@enduml"""

# Diagram 7: Security Sandbox
diagrams["sandbox"] = """@startuml
!theme plain
skinparam backgroundColor #FFFFFF
skinparam roundCorner 8
skinparam defaultFontName "Helvetica", "Arial", sans-serif

package "Host / Studio App (app.vibeshorts.com)" as host_app #E1F5FE {
  component "Next.js Web Client\\n- User session & auth cookies\\n- Access token in memory\\n- Firestore listeners" as client_ui
  
  package "Sandboxed Preview Iframe (preview.vibeshorts-render.net)" as iframe_box #FFF3E0 {
    component "Isolated Player Container\\n<iframe sandbox=\\"allow-scripts\\">\\n- Separate origin\\n- NO cookies / NO local storage access\\n- Narrow postMessage API (seek, play, pause)" as iframe_player
  }
}

package "Worker Host Environment (Cloud Run Service)" as worker_env #EDE7F6 {
  component "Execution Wrapper\\n- Fetches immutable package from GCS\\n- Spawns Sandboxed Cloud Run Job" as wrapper
}

package "Isolated Render Sandbox (Cloud Run Job)" as render_sandbox #FFCDD2 {
  component "Sandboxed Chromium & HyperFrames CLI" as headless_browser
  
  folder "/workspace (Read-Only Ephemeral)" as sandbox_fs {
    file "index.html"
    file "manifest.json"
    file "assets/*.mp4"
    file "assets/*.wav"
  }
  
  note bottom of render_sandbox
    STRICT CONTAINER ENFORCEMENT:
    - NO outbound internet access
    - NO GCP Instance Metadata access (169.254.169.254 blocked)
    - NO provider API keys or Firebase Admin credentials
    - Capped memory (2GB) & deterministic frame clock
  end note
}

client_ui --> iframe_player : Restricted postMessage channel
wrapper --> render_sandbox : Mounts materialized package
headless_browser --> sandbox_fs : Reads local files only
headless_browser --> wrapper : Emits rendered frames -> MP4
@enduml"""

# Diagram 8: ER Diagram
diagrams["er"] = """@startuml
!theme plain
skinparam backgroundColor #FFFFFF
skinparam shadowing false
skinparam roundCorner 6
skinparam defaultFontName "Helvetica", "Arial", sans-serif

entity "Project" as proj {
  * project_id : string <<PK>>
  --
  * owner_uid : string
  * brand_version : number
  * created_at : timestamp
}

entity "BrandBundle" as brand {
  * id : string <<PK>>
  * version : number <<PK>>
  --
  * colors : JSON
  * fonts : JSON
  * logo_artifact_id : string
  * visual_style_tags : string[]
}

entity "Run" as run {
  * run_id : string <<PK>>
  --
  * project_id : string <<FK>>
  * user_id : string
  * status : RunState
  * spend_cap_cents : number
  * storyboard_artifact_id : string <<FK>>
  * adk_session_id : string
  * version : number
}

entity "Step" as step {
  * step_id : string <<PK>>
  --
  * run_id : string <<FK>>
  * required_step_ids : string[]
  * status : StepState
}

entity "Job" as job {
  * job_id : string <<PK>>
  --
  * step_id : string <<FK>>
  * run_id : string <<FK>>
  * idempotency_key : string
  * status : JobState
  * claim_lease_owner : string
  * claim_expiry : timestamp
  * fencing_generation : number
  * provider_op_ref : JSON
}

entity "ArtifactRevision" as artifact {
  * id : string <<PK>>
  --
  * project_id : string <<FK>>
  * run_id : string <<FK>>
  * job_id : string <<FK>>
  * parent_id : string <<FK>>
  * input_artifact_ids : string[]
  * type : ArtifactType
  * storage_uri : string
  * content_sha256 : string
  * created_at : timestamp
}

entity "Approval" as approval {
  * approval_id : string <<PK>>
  --
  * target_artifact_id : string <<FK>>
  * reviewer_uid : string
  * type : GateType
  * decision : decision_enum
  * timestamp : timestamp
}

entity "LedgerEntry" as ledger {
  * entry_id : string <<PK>>
  --
  * job_id : string <<FK>>
  * project_id : string <<FK>>
  * estimated_cents : number
  * reserved_cents : number
  * settled_cents : number
  * is_uncertain : boolean
  * rate_snapshot : JSON
}

proj ||--o{ brand : "has versions"
proj ||--o{ run : "contains"
run ||--o{ step : "executes"
step ||--o{ job : "spawns"
job ||--o{ artifact : "produces"
artifact ||--o{ artifact : "references"
run ||--o{ approval : "waits for"
approval ||--|| artifact : "binds to revision"
job ||--o{ ledger : "reserves & settles"
@enduml"""

# Diagram 9: Budget Flow
diagrams["budget"] = """@startuml
!theme plain
skinparam backgroundColor #FFFFFF
skinparam shadowing false
skinparam roundCorner 6
skinparam defaultFontName "Helvetica", "Arial", sans-serif

participant "Job Submission" as Sub #E1F5FE
database "Budget Ledger\\n(Firestore)" as Ledger #FFF9C4
participant "External Provider\\n(Vertex AI)" as Prov #FCE4EC

== 1. Atomic Pre-Reservation ==
Sub -> Ledger: Check (Project Available Balance >= Estimated Cost)
alt Insufficient Balance / Cap Exhausted
  Ledger --> Sub: REJECT with BUDGET_EXHAUSTED error
  note right: Work is prevented before\\ncalling external API!
else Sufficient Balance
  Sub -> Ledger: Atomically create LedgerEntry:\\n[reserved = $1.50, settled = $0.00, uncertain = false]
  Ledger --> Sub: Reservation Confirmed (Hold locked)
end

== 2. Provider Invocation ==
Sub -> Prov: Call paid generation (e.g. Veo video plate)

== 3. Settlement or Uncertainty ==
alt Normal Completion
  Prov --> Sub: Video output ready + Token/second usage
  Sub -> Ledger: Update LedgerEntry:\\n[settled = $1.42, reserved = $0.00, status = settled]
  note right: Excess reserved hold is\\nreleased back to project!
else Provider Crash / Disconnect (Status Unknown)
  Prov --x Sub: Network dropped / timeout
  Sub -> Ledger: Update LedgerEntry:\\n[is_uncertain = true, reserved = $1.50 retained]
  note right of Ledger #FFCDD2
    UNCERTAIN LIABILITY:
    Reservation is NOT refunded until
    Cloud Scheduler reconciles the charge!
  end note
end
@enduml"""

# Diagram 10: Provider Routes
diagrams["routes"] = """@startuml
!theme plain
skinparam backgroundColor #FFFFFF
skinparam roundCorner 8
skinparam defaultFontName "Helvetica", "Arial", sans-serif

package "Vertex AI Route (Cloud Run Default)" as pkg_vertex #E8F5E9 {
  class "Vertex Image" as vi {
    Model: gemini-2.5-flash-image
    Status: GA Baseline
    Execution: Synchronous
    Outputs: Raw parts / PNG
  }
  class "Vertex Video" as vv {
    Model: veo-3.1-generate-001
    Status: GA
    Execution: Long-Running Operation (us-central1)
    Outputs: MP4, 24fps, GCS output
  }
  class "Vertex Music" as vm {
    Model: lyria-002
    Status: GA Baseline
    Execution: predict (global)
    Outputs: WAV 48kHz (up to 32.8s)
  }
}

package "Gemini Developer API Route (Secret Manager Key)" as pkg_dev #FFF3E0 {
  class "Developer Image" as di {
    Model: gemini-2.5-flash-image
    Status: Legacy Baseline
    Execution: Synchronous
  }
  class "Developer Video" as dv {
    Model: veo-3.1-generate-preview
    Status: Preview
    Execution: LRO (2-day ephemeral retention)
  }
  class "Developer Music" as dm {
    Model: lyria-3-clip-preview
    Status: Preview
    Execution: Interaction API
    Outputs: 30s MP3 44.1kHz
  }
}

note bottom
  IMMUTABLE JOB SNAPSHOT:
  Each accepted job permanently snapshots its route, model, location, and capability profile.
  Retries NEVER silently swap between Vertex and Developer routes.
end note
@enduml"""

# Test each diagram URL
urls = {}
for name, puml in diagrams.items():
    svg_url = plantuml_url(puml, 'svg')
    uml_url = plantuml_url(puml, 'uml')
    urls[name] = {"svg": svg_url, "uml": uml_url, "puml": puml}
    try:
        req = urllib.request.Request(svg_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[{name}] SVG Verified: Status {resp.status}")
    except Exception as e:
        print(f"[{name}] ERROR: {e}")

print("All tested.")
