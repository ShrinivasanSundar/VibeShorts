# VibeShorts Product Requirements Document

| Field | Value |
| --- | --- |
| Product | VibeShorts |
| Document version | 1.0 |
| Prepared | 5 October 2026 |
| Status | Draft requirements consolidated from repository documentation |
| Current baseline | Implemented local fixture Studio; live providers and production deployment pending validation |
| Intended release | A private, brand-aware short-video Studio with MCP access, human review, editable compositions, and durable execution |

## 1. Product definition

VibeShorts turns a natural-language brief into a brand-aware storyboard, generated media, an editable HyperFrames composition, and a private rendered short. Creators work through a browser Studio; authorized external agents use MCP. Both interfaces share the same application contracts, permissions, job lifecycle, and accounting.

One Google ADK Creative Director makes creative decisions. Application services control execution, dependencies, authorization, spending, cancellation, recovery, and publication. A human approves the storyboard before paid media production and the exact composition before final export.

This document consolidates product intent and release requirements. It does not certify features as production-ready. Implementation status comes from [STUDIO.md](docs/STUDIO.md), and historical verification comes from [VALIDATION.md](docs/VALIDATION.md). The latest recorded verification is 4 October 2026; no tests or live calls were rerun to prepare this document.

## 2. Problem and users

The product addresses a workflow in which creators must coordinate image generation, video generation, music, brand assets, editing, and exports across separate tools. Repeating an entire workflow for one scene change wastes time and paid capacity. Unclear operation status, lost revisions, and unexpected retries make automated production difficult to trust.

The following personas are inferred from the documented workflows; user research and market sizing are not recorded in the repository.

| User | Need | Primary workflow |
| --- | --- | --- |
| Founder or marketer | Produce a short product launch or social ad using exact brand assets | Brief → storyboard review → preview → export |
| Creator or editor | Adjust copy, pacing, audio, or individual scenes without rebuilding everything | Timeline edit or scene revision → save → review → export |
| Developer or agent integrator | Invoke media and video workflows from an external agent with predictable contracts | OAuth consent → MCP submission → job/run reads → private asset retrieval |
| Project owner or reviewer | Control project access, spending, and approved revisions | Membership, brand configuration, and version-bound review |
| Operator | Diagnose failed or uncertain work and validate deployment | Job inspection, recovery, reconciliation, and access revocation |

## 3. Goals and boundaries

### 3.1 Goals

1. Produce a reviewed, editable short from one brief and a versioned brand bundle.
2. Give users control over the production plan, final composition, and approved spend.
3. Make browser, REST, MCP, and native director submissions behave consistently.
4. Preserve progress across process restarts and avoid blind repurchase after uncertain provider submissions.
5. Support precise edits and selective scene regeneration while retaining unaffected work.
6. Keep project media private and make current state, costs, and required decisions understandable.

The flagship acceptance workflow is a 15-second product launch with 3–5 scenes. The first output profile is vertical 9:16, 720×1280, 24 fps, H.264 MP4 with AAC stereo audio. Landscape 16:9 is part of the storyboard contract and must be validated for its selected provider/output configuration. The existing six-second fixture export demonstrates orchestration, not completion of the live 15-second creative-quality acceptance goal.

### 3.2 Excluded from the initial release

- Automatic final export without human preview approval.
- An external agent approving a user's work or performing operator reconciliation.
- Arbitrary unvalidated executable compositions with broad network or credential access.
- Silent model substitution, automatic safety bypass, or unbounded creative retry loops.
- Specialist-agent orchestration without evidence that it improves outcomes.
- Neural brand scoring, an organization-wide shared asset library, and a template catalog.
- A promise of exact model reproducibility or a guaranteed ceiling on external provider billing.

Social publishing, subscription pricing, voiceover production, billing reconciliation automation, and organization administration have no committed delivery scope in the reviewed docs. Retaining native video audio, voiceover, or music ducking requires an explicit audio policy and a new reviewed composition.

## 4. Current product baseline

“Implemented” below means reported by the repository documentation. It does not mean independently verified in this review or validated with live credentials.

| Capability | Documented status | Remaining evidence |
| --- | --- | --- |
| API/MCP, Firebase identity, OAuth, job accounting and recovery | Implemented; local transport/emulator tests recorded | Production credentials, IAM, signing, and deployed endpoints |
| Image/video/music jobs and media preparation | Implemented; fixtures and adapter tests | Actual Vertex/Developer responses, quota, safety, and availability |
| Typed storyboard and two review gates | Implemented; exact-revision tests recorded | Live director output and browser review interactions |
| HyperFrames packages and private exports | Implemented; actual fixture MP4 recorded | Container builds, cloud rendering, deployed isolation, signing |
| Timeline and natural-language edits | Implemented; frontend compilation and backend tests recorded | End-to-end browser interaction and general live director edits |
| Selective scene revisions and dependency traversal | Implemented; backend tests recorded | Live media reuse and continuity-quality review |
| Versioned brand assets and deterministic checks | Implemented | Creative brand-quality evaluation; neural scoring remains future work |
| Project members, three policies, locale requests, batch briefs | Implemented foundations | Full user-facing acceptance and live locale/font quality |
| Persistent ADK sessions and result bridge | Implemented; isolated persistence/bridge checks recorded | Target-environment/live integration and upgrade validation |
| Organization asset libraries and template catalog | Roadmap | Product design, implementation, and evaluation |

The current director produces a typed plan; the application scheduler owns production jobs and approval pauses. The asynchronous ADK result bridge is available to tool bindings. The roadmap's fully resumed tool-driven director flow must not be treated as proof that every production step currently uses that path.

## 5. User experience and journeys

### 5.1 First short

1. Sign in with Google through Firebase and create or select an authorized project.
2. Configure brand colors, exact logos/fonts, image references, and policy text; optionally import assets.
3. Enter a brief, duration, aspect ratio, creative policy, locale, and a spend cap where supported.
4. Receive a typed storyboard with scene objectives, exact copy, visual prompts, timing, references, and music intent.
5. Review and approve that storyboard revision and its production allowance. Planning itself may consume director budget before this gate; paid media production follows approval.
6. Follow durable job progress in Activity while images, video plates, music, and media preparation complete.
7. Inspect the composition preview for product identity, text, branding, pacing, and audio.
8. Save any edits, then approve the exact current composition revision.
9. Download the validated private MP4 and editable package ZIP from Exports.

### 5.2 Editing and scene revision

The creator can adjust timeline position, trim points, duration, tracks, copy, visibility, volume, and fades. Local undo/redo supports iteration; Save publishes a new immutable package against the expected current head. A competing save returns a conflict.

Natural-language fixture edits cover quoted copy replacement, title, mute, aspect ratio, colors, and shortening. General edits use the configured director. A scene request such as `scene scene-1: a warmer product reveal` creates a revised run, reuses unaffected scenes/music, and rebuilds changed scenes and their transitive continuity dependencies. That run passes both review gates again. Composition-only edits require fresh preview approval.

### 5.3 External agent workflow

The client obtains a resource-bound MCP token through Firebase-backed OAuth, explicit project selection, scopes, and PKCE. It submits a command and receives durable identifiers, reads progress, follows authenticated review links when human decisions are needed, and retrieves authorized artifacts after completion. A queued job handle is never presented as finished media.

### 5.4 Failure and recovery

Users see actionable failures, cancellation state, or a reconciliation requirement. Known provider operations resume polling or materialization after a restart. A request that may have been accepted without a saved handle retains its financial liability and requires reconciliation before repurchase. Previously accepted work may still complete or incur cost after cancellation.

## 6. Functional requirements

Priorities express release importance, not implementation status: **P0** is required for the core release; **P1** extends the core experience and may already have implemented foundations; **P2** is future platform scope.

### 6.1 Identity, projects, and private access

| ID | Priority | Requirement | Acceptance |
| --- | --- | --- | --- |
| FR-01 | P0 | Require verified, enabled Firebase identity, app access, and project/action permission for protected operations. Derive UID from credentials. | Missing/invalid credentials return 401; insufficient permission returns 403; no unauthorized job or reservation is created. |
| FR-02 | P0 | Support project creation and authorized membership with server-controlled access/roles. | A new sign-in has no access to other users' projects; forged UID or project references cannot grant access. |
| FR-03 | P0 | Keep storage private and authorize object-specific access. | Download grants default to five minutes; unauthorized asset/path requests fail. Membership removal blocks new grants. |
| FR-04 | P0 | Recheck access before consequential background work; revocation stops new work and linked MCP access. | Expired browser tokens do not alone cancel accepted work; disabled access or removed membership triggers cancellation/reconciliation policy. |

Previously issued signed URLs remain usable until expiry; immediate read revocation requires authenticated delivery. Browser Security Rules default to deny, allow only authorized summary reads, and deny direct writes to jobs, budgets, approvals, sessions, and provider state.

### 6.2 Brand and assets

| ID | Priority | Requirement | Acceptance |
| --- | --- | --- | --- |
| FR-05 | P0 | Maintain immutable brand revisions containing colors, exact font/logo references, image references, and creative policy. | Runs snapshot a brand version; updates affect future runs unless an explicit revision adopts them. |
| FR-06 | P0 | Verify imported image, font, audio, and MP4 content before readiness. | Validate ownership, MIME/content, size, and completion; imports use server-selected object destinations. |
| FR-07 | P0 | Package authorized exact brand assets and validate required references. | Logos and typography are controlled overlays rather than generated branded lettering; exports retain valid bundled assets. |
| FR-08 | P1 | Provide bounded asset listing and reusable revision history. | Listing uses opaque query-bound cursors, defaults to 20 items, and never exceeds 100 per page. Superseded assets remain accessible only under project policy. |

Documented import limits are 7 MB for images, 2 MB for fonts, and 200 MB for audio/video, with media duration up to 125 seconds. Upload completion must occur within the documented five-minute window. These import limits do not imply the same limits for generated provider outputs.

### 6.3 Director and storyboard

| ID | Priority | Requirement | Acceptance |
| --- | --- | --- | --- |
| FR-09 | P0 | Use one Creative Director to turn a brief and trusted project/brand context into a typed storyboard. | Preserve trusted identifiers; record model, prompt/policy version, and session/invocation correlation. |
| FR-10 | P0 | Validate scene timing, references, dependencies, and supported provider combinations before production. | The flagship plan has 3–5 scenes; director policy limits each scene to 8 seconds; editorial timing matches the requested total, accounting for overlaps. Cycles or unauthorized references fail validation. |
| FR-11 | P0 | Record exact overlay copy, scene objective/prompt, references, continuity links, aspect ratio, fps, and music intent. | The plan is an immutable artifact; provider source duration is distinct from editorial cut duration. Overlay lines follow the director policy's limit of fewer than 120 characters. |
| FR-12 | P1 | Support `product_launch`, `explainer`, and `social_ad` policies, locale requests, and batch brief submission. | Each brief produces its own governed workflow; locale-specific output is reviewed and fonts cover the requested script. |

Product launch emphasizes reveal, benefit, and CTA; explainer uses one clear idea per scene; social ad uses a hook and concrete CTA. Locale requests are implemented foundations, not a guarantee of complete cross-language production quality. Bundled Inter covers Latin text; other scripts require appropriate uploaded fonts.

### 6.4 Production and media preparation

| ID | Priority | Requirement | Acceptance |
| --- | --- | --- | --- |
| FR-13 | P0 | Generate images, first-frame-constrained video plates, and reviewed instrumental music as durable jobs. | Application submissions return handles even when the upstream provider is synchronous; artifacts are published only after durable storage and verification. |
| FR-14 | P0 | Make provider route/model/location/capability configuration explicit and snapshot accepted settings. | No retry silently changes route/model; unsupported combinations fail before paid submission where feasible. |
| FR-15 | P0 | Inspect, trim, crop/scale, normalize fps/audio, and create derivatives while retaining sources. | Prepared outputs match the composition profile; Veo plate audio is muted by default in favor of the reviewed music bed. |
| FR-16 | P0 | Model shot continuity through immutable extracted-frame dependencies. | The next scene uses the last displayed editorial frame of the preceding trimmed plate, not the untrimmed source end. |
| FR-17 | P0 | Materialize completed provider output into project-owned storage promptly. | Expiring provider URLs are not embedded as persistent composition dependencies; MIME, dimensions, duration, and hashes are checked. |

Vertex uses server ADC/workload credentials; Developer uses an explicit server API key. Fixture mode uses emulators and synthetic media without paid calls. Baseline model names are dated configuration references from the source docs, not guaranteed current availability. Capabilities must disclose route, model, verification date, constraints, and deprecation status.

### 6.5 Composition, editing, approvals, and export

| ID | Priority | Requirement | Acceptance |
| --- | --- | --- | --- |
| FR-18 | P0 | Publish immutable HyperFrames packages with every input revision and file hash. | Packages contain locally bundled media, fonts, runtime dependencies, and fixed output settings; preview and export use the same package. |
| FR-19 | P0 | Support timeline editing, seeking/zoom, undo/redo, and expected-head Save. | Position, trims, duration, tracks, copy, volume/fades, visibility, and deletion persist in a new revision; concurrent writes conflict rather than overwrite. |
| FR-20 | P0 | Support selective scene revisions and transitive dependency invalidation. | Unaffected scenes/music are reused; downstream continuity anchors/plates and derived compositions are rebuilt when their inputs change. |
| FR-21 | P0 | Bind storyboard and preview approvals to exact targets, authorized reviewers, and decision records. | Stale/conflicting approval requests fail; an agent cannot grant approval; an edited target needs a new approval. |
| FR-22 | P0 | Require saved edits and exact current-package approval before final export. | Approval of revision 1 cannot authorize revision 2; a later head cannot silently replace the accepted render input. An older export is not promoted as current. |
| FR-23 | P0 | Validate structural composition quality and final MP4 readiness. | Wrong streams, duration/dimensions, missing audio, or blank-frame failures prevent a ready export and identify the responsible step. |
| FR-24 | P0 | Provide private MP4 and editable ZIP downloads. | Download content matches registered hashes and project ownership; packages remain renderable after provider URLs expire. |

Creative review must assess product identity, readable copy, exact branding, safe zones, pacing, and audio. Structural checks alone do not establish creative quality. The documented repair policy targets at most one automatic creative revision per failing scene; further attempts require a user decision and remaining budget. A still-image motion fallback needs explicit user acceptance.

### 6.6 MCP and shared contracts

| ID | Priority | Requirement | Acceptance |
| --- | --- | --- | --- |
| FR-25 | P0 | Expose Streamable HTTP at `/mcp` and authenticated local stdio through shared commands. | Native/REST/MCP submissions use identical permissions, validation, idempotency, and accounting semantics. |
| FR-26 | P0 | Provide Firebase-backed OAuth with discovery, PKCE S256, consent, registered clients, scopes, and resource-bound tokens. | Reject wrong audiences, revoked grants, code replay, and incorrect PKCE; Firebase ID tokens are not accepted as generic `/mcp` bearer tokens. |
| FR-27 | P0 | Return typed jobs/results and stable useful errors with bounded context. | MCP tools declare output schemas and return structured output plus compatible JSON text; errors do not leak secrets or other-project state. |
| FR-28 | P0 | Expose only capabilities backed by common application handlers. | Read calls return directly; long operations return durable job handles with polling guidance. Human review is linked through the app. |

The documented core tool families are brand/context (`get_brand_dna`, `get_project_context`, `list_assets`, `get_asset`, `get_capabilities`), generation (`generate_image`, `generate_video`, `generate_music`), media (`inspect_media`, `extract_frame`, `prepare_media`), composition (`get_hyperframe`, `create_hyperframe`, `update_hyperframe`, `render_hyperframe`), and lifecycle (`create_video`, `get_job`, `get_run`, `cancel_job`, `cancel_run`). Actual discovery is authoritative for the exposed catalog; a diagram heading is not a tool-count contract.

### 6.7 Durability, budgets, and cancellation

| ID | Priority | Requirement | Acceptance |
| --- | --- | --- | --- |
| FR-29 | P0 | Commit idempotency, jobs, reservations, and dispatch outbox atomically. | Same project/command/key and input returns existing IDs; changed input conflicts; crash before publication is recovered through the outbox. |
| FR-30 | P0 | Use leased, fenced execution and persisted provider operation/poll state. | Duplicate dispatch cannot commit a second current transition; late or stale workers cannot overwrite the head. |
| FR-31 | P0 | Preserve uncertain submissions and their liability without blind retries. | Missing handle after possible acceptance becomes `submission_unknown`/`needs_reconciliation`; a known handle with retrieval failure resumes retrieval. |
| FR-32 | P0 | Reserve against run, shared project, and account allowances before paid work. | Parallel reservations are atomic; replay does not reserve twice; client caps cannot raise server allowances; uncertainty retains the reservation. |
| FR-33 | P0 | Record integer micro-USD estimates, reservations, settlements, usage, and rate snapshots. | Settlement occurs once; usage estimates remain labeled until billing reconciliation; cancellation does not erase incurred costs. |
| FR-34 | P0 | Persist approvals, dependencies, and session state without resident waiting processes. | Restart during an approval or job wait retains context; session ownership/version checks and serialized delivery prevent concurrent conflicting invocations. |
| FR-35 | P0 | Stop new steps promptly on cancellation and provide operator recovery tools. | Keep accepted operation/cost records; use provider cancellation only when supported; reconciliation records identity and evidence. |
| FR-36 | P0 | Bound execution concurrency and retrieval retries. | Validate the documented initial limits of two concurrent video submissions and one active final render per project; provider quota can impose stricter limits. |

The budget model covers generation, director planning, preparation, draft/final rendering, and retries. Live video/music/director/render operations require positive reviewed ceilings in the rate profile; video reservations conservatively cover eight source seconds. Admission estimates are not a guarantee that provider invoices equal those estimates. One-minute authenticated sweeps are the specified production recovery cadence.

## 7. Nonfunctional requirements

| ID | Area | Release requirement |
| --- | --- | --- |
| NFR-01 | Privacy | Keep provider keys, Admin credentials, user tokens, raw session events, and private reasoning out of browser summaries, queue payloads, and logs. |
| NFR-02 | Preview isolation | Treat HTML/JavaScript as executable content; require isolated preview origin/sandbox, no app credentials, and narrowly validated playback messages. |
| NFR-03 | Render isolation | Allow only the materialized package and approved dependencies; block arbitrary filesystem/network/metadata access and credential exposure; bound CPU, memory, duration, and output size. Demonstrate these controls in the deployed environment. |
| NFR-04 | Consistency | Separate immutable revisions, ancestry, dependency edges, and current-head state; preview and export pin exact package/runtime inputs. |
| NFR-05 | Determinism | Use frame-based seeking and fixed output settings; avoid wall-clock and render-time network dependencies. Compare representative preview/export frames. |
| NFR-06 | Compatibility | Pin dependencies and record tested SDK/protocol/schema/browser/runtime versions; validate upgrades with recovery and integration checks. |
| NFR-07 | Observability | Correlate commands, jobs, attempts, revisions, provider calls, and renders; track queue age, leases, polling, uncertainty, spend, failures, and access denial. |
| NFR-08 | Usability | Show real operation state and decision prompts; clear subscriptions/project caches on sign-out; do not invent percentage progress. |
| NFR-09 | Licensing | Preserve required license/copyright notices for distributed font software, including the bundled Space Grotesk and DM Sans SIL OFL files. |

No production latency SLO, availability target, retention period, or formal accessibility target is established by the docs. These are release decisions to set during pilot validation, rather than invented guarantees. Acceptance should include keyboard operation of review/edit controls and clear failure/conflict states, with the final accessibility standard still to be chosen.

## 8. Data and system responsibilities

| Record/component | Product responsibility |
| --- | --- |
| Project and membership | Ownership, allowed actions, current brand/head, scoped budgets |
| Brand revision | Immutable creative inputs and exact asset references |
| Run | Brief, policy/brand snapshots, overall status, spend cap, session correlation |
| Step | Dependency node and exact input/output revisions |
| Job/provider operation | Execution segment, attempt, lease/fence, accepted handle, polling, reservation |
| Artifact revision | Verified immutable output, hash, storage ownership, ancestry and input edges |
| Approval | Human reviewer, target revision, decision/time, accepted budget/version |
| Ledger/outbox | Financial state and reliable dispatch |
| ADK session/events | Conversation and invocation history with project/user ownership |
| Browser summaries/events | Sanitized projection of application state, not a separate source of execution truth |

The deployment design uses Next.js Studio and FastAPI/MCP, Firebase Authentication, Firestore, private Cloud Storage, Pub/Sub, Cloud Scheduler, Cloud Run services/jobs, Secret Manager, and cloud logging/tracing. FFmpeg prepares media; HyperFrames performs final composition rendering. The custom Firestore ADK adapter is project-owned, not a presumed built-in SDK service. ADK uses a separate locked Python environment from the MCP backend.

## 9. Measurement and success criteria

The docs contain acceptance evidence, not production usage baselines. The following measurements are proposed for pilot evaluation; numeric business targets remain uncommitted.

| Measure | Definition | Purpose |
| --- | --- | --- |
| Approved-export completion | Started authorized briefs that yield an approved, validated export; cancellations and failures reported separately | End-to-end usefulness |
| Time to storyboard / preview / export | Per-stage elapsed time, excluding human waiting where relevant | Identify production bottlenecks |
| First-review acceptance | Storyboards and previews approved without creative revision | Creative quality |
| Revision efficiency | Reused eligible artifacts and avoided regeneration on selective edits | Demonstrate lower repeat work |
| Cost per approved export | Estimated/settled/uncertain amounts reported separately by run and operation | Budget transparency |
| Recovery correctness | Duplicate purchases, stale publications, lost approvals, unresolved submissions | Trust and operational readiness |
| Security correctness | Unauthorized reads/writes and approval bypasses in the acceptance suite | Private project boundaries |

Release invariants are zero unauthorized approvals, zero stale-revision overwrites, and no duplicate paid purchases from replay or automatic uncertainty retries in controlled acceptance scenarios. They are correctness gates, not a claim about all external side effects under every failure.

## 10. Acceptance and validation plan

### 10.1 Recorded local evidence

[VALIDATION.md](docs/VALIDATION.md) records 60 backend tests, six emulator tests, three browser Security Rules tests, isolated ADK session/result-bridge checks, frontend TypeScript/build checks, and a complete OAuth/MCP fixture export. The recorded MP4 is six seconds, 720×1280, 24 fps, H.264 with stereo 48 kHz AAC. A rendered frame and standalone HyperFrames checks were inspected.

The fixture acceptance program creates its own synthetic user/project and automatically records fixture-only review decisions. This is not permission for automatic approval in normal app workflows. No live provider call or deployment is recorded; container builds, deployed isolation, actual Studio browser interaction, and production signing remain unverified.

### 10.2 Required release scenarios

| Scenario | Pass condition | Requirements |
| --- | --- | --- |
| Live flagship short | Real director produces a valid 15-second plan; a person approves both targets; image/video/music complete; private export matches the reviewed package and output profile | FR-09–17, FR-21–24 |
| Unauthorized or revoked identity | Invalid credentials, forged UID/session/path, wrong project, removed membership, and revoked MCP grants cannot read, submit, approve, or obtain new URLs | FR-01–04, FR-26 |
| Browser rules and cache cleanup | Cross-project reads and direct operational writes fail; sign-out removes subscriptions and project state | FR-01–04, NFR-08 |
| Replay and transport parity | Same input/key returns the same work/reservation through supported adapters; changed input conflicts | FR-25, FR-27–30 |
| Dispatch/worker crash | Recover committed unsent work, duplicate messages, expired pre-submission claims, and stored candidates without stale publication | FR-29–30, FR-34 |
| Provider uncertainty and polling | Missing handle retains liability without repurchase; a known handle resumes polling/materialization | FR-31, FR-33 |
| Approval persistence | Restart during either human gate preserves exact targets; conflicting or stale decisions fail | FR-21–22, FR-34 |
| Concurrent edits | Studio/director competing saves conflict; local user work and current head are not overwritten | FR-18–22 |
| Selective revision | Changed scene and its continuity descendants rebuild; unrelated scenes/music reuse valid revisions; both run gates return | FR-16, FR-20–21 |
| Budget and cancellation | Parallel work cannot bypass allowances; cancellation stops new steps while preserving accepted charges and uncertain liability | FR-32–36 |
| Provider quality failure | Unsupported combinations, safety filtering, missing output, or quota failure produce actionable errors without concealed fallback | FR-14, FR-17, FR-27 |
| Private export and isolation | Validate object privacy/signing, package hashes, forbidden network/file access, resource limits, and preview/export frame parity | FR-03, FR-18, FR-23–24, NFR-02–05 |
| Browser edit workflow | Exercise sign-in, imports, brand saves, timeline/undo/redo, conflicts, approvals, and MP4/ZIP downloads in an actual browser | FR-05–07, FR-19, FR-21–24 |

Reproducible fixture and local checks are documented in [SETUP.md](docs/SETUP.md) and [STUDIO.md](docs/STUDIO.md). Paid image acceptance is explicitly opt-in after offline preflight. A passing preflight does not establish IAM, billing, bucket privacy, model availability, or full-video readiness.

## 11. Release sequence and dependencies

| Stage | Scope | Exit criterion |
| --- | --- | --- |
| Local fixture baseline | Existing Studio, common tools, emulators, real fixture render | Repeat recorded acceptance and complete actual browser interaction testing |
| Live provider validation | Vertex default route; explicit Developer route where intended | Authorized paid image smoke followed by budgeted video/music/director tests with verified availability and ownership |
| Private cloud pilot | HTTPS origins, Firebase domains, OAuth callbacks, rules/indexes, private storage, queue/scheduler, renderer | Build containers; prove IAM/signing/isolation; pass core release scenarios and review creative quality |
| Editing and policy hardening | Selective revisions, general natural-language edits, multiple policies, locale/batch foundations | Evaluate browser conflicts, artifact reuse, live policy output, and script/font coverage |
| Brand/platform extensions | Neural assessment, templates, organization asset sharing, broader localization | Define evaluation and permissions first; add capabilities through common commands |

These stages reconcile the original phase roadmap with the newer implementation record: several later-phase foundations already exist, but live validation and production hardening are still release work. No delivery dates, commercial launch, or paid execution are authorized by this document.

## 12. Risks and open decisions

| Risk or decision | Required resolution |
| --- | --- |
| Model retirement, availability, location, quota, pricing | Recheck before live acceptance; explicitly version configuration/capability/rate changes. The baseline image model is flagged as deprecated. |
| Estimated spend differs from invoices | Review conservative operation ceilings, account/project/run controls, and operator reconciliation evidence. |
| Executable preview/render content | Prove deployed isolation; Cloud Run alone does not establish the complete sandbox contract. |
| Live creative output quality | Evaluate product fidelity, copy, typography, safety, music, and continuity with human reviewers. |
| Browser workflows lack interaction evidence | Run the actual Studio acceptance journey, including save conflicts, approvals, and private downloads. |
| Director resume topology | Keep the implemented typed-plan scheduler path explicit; validate deferred result delivery before expanding tool-driven orchestration. |
| Retention and deletion | Define asset/candidate/session retention, cleanup, user deletion, and audit requirements before broad production rollout. |
| Collaboration and scale | Decide richer role semantics, organization ownership, batch limits, concurrency policy, and production SLOs. |
| Dependencies and runtime upgrades | Recheck advisory/compatibility records and require recovery, rules, and render regressions before upgrading. |

## 13. Source traceability and interpretation

| Repository document | Contribution |
| --- | --- |
| [README.md](README.md) | Product vision, architecture, contracts, media/output profile, approvals, budgets, recovery, roadmap, and required acceptance scenarios |
| [VISUAL-README.md](VISUAL-README.md) | Visual system/dependency/state models and isolation blueprint |
| [STUDIO.md](docs/STUDIO.md) | Current implementation scope, editing/import behavior, live configuration, renderer routes, and remaining validation |
| [SETUP.md](docs/SETUP.md) | Local/cloud prerequisites, identity/MCP configuration, testing, operator recovery, and opt-in paid acceptance |
| [COMPATIBILITY.md](docs/COMPATIBILITY.md) | Pinned compatibility baseline, protocol behavior, historical local acceptance, and upgrade caveats |
| [VALIDATION.md](docs/VALIDATION.md) | Recorded 4 October 2026 verification and explicit untested areas |
| [Director policy](skills/product_launch/director.md) | Scene/copy constraints, exact brand overlays, policy intent, continuity ordering, and approval boundaries |
| [Web AGENTS.md](apps/web/AGENTS.md) and [CLAUDE.md](apps/web/CLAUDE.md) | Framework-specific contributor instructions; no additional product scope |
| [Space Grotesk license](apps/web/app/fonts/Space-Grotesk-OFL.txt) and [DM Sans license](apps/web/app/fonts/DM-Sans-OFL.txt) | Font-distribution notice requirements |

When sources differ, this PRD uses the newer Studio/validation record for implementation status and the main specification for normative contracts. Specifically:

- All money uses integer micro-USD; the visual ER diagram's cents labels are illustrative inconsistencies.
- A known provider handle with polling failure triggers retrieval recovery, not an automatic uncertain-submission classification or a new purchase.
- Provider lookup/idempotency recovery is conditional on documented support; illustrative diagram arrows do not establish such a facility.
- The visual “15 tools” heading is not authoritative; its table lists a broader core surface, and actual discovery governs implementation.
- Preview/render isolation diagrams are requirements, not evidence of a validated cloud sandbox.
- A verified six-second fixture is distinct from the live 15-second flagship goal.
- Personas, pilot metrics, and unresolved commercial/operational decisions are synthesis rather than claims of completed research or committed targets.
