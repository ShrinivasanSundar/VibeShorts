# Studio and complete fixture workflow

VibeShorts now includes the MCP service, REST API, durable execution, Firebase identity/OAuth, and a Next.js Studio. The fixture workflow runs without model credentials and exports an actual HyperFrames MP4. Live adapters are configurable, but their calls and deployment have not been exercised with your credentials.

## Start locally

Install Python 3.12, uv, Node 22.19+, JDK 21 and FFmpeg. See [SETUP.md](SETUP.md) for Java setup, Firebase configuration and OAuth clients.

```sh
uv sync --frozen
uv sync --project agents/creative_director --frozen
npm ci
cp .env.example .env
cp apps/web/.env.example apps/web/.env.local
npm run emulators
```

In another terminal, run `bash scripts/dev.sh`. This starts API/MCP on port 8000, the queue worker and Studio on port 3000. It creates missing local env files without replacing existing files. Google sign-in uses the Firebase Auth emulator in this configuration. Keep all emulator services running while using Studio.

After signing in, create a project. Enter a brief in the Director panel and generate a short. Review the storyboard before production starts. Follow progress in Activity; review the completed preview before approving final export. Download the private MP4 and editable ZIP in Exports.

Assets supports verified image, audio, MP4 and font imports. Image uploads have a 7 MB limit, fonts 2 MB and audio/video 200 MB, with a maximum supported media duration of 125 seconds. Brand settings persist immutable revisions with exact logo/font references, colors, image references and policy text.

The timeline supports positioning, trim points, duration, track placement, exact copy, volume/fades, visibility, deletion, zoom, seeking and undo/redo. Save creates a new immutable package using the expected current head. A competing save conflicts. Final export requires approval of the exact current package. Pending local edits must be saved first.

Fixture natural-language edits support quoted copy replacement, title, mute, aspect ratio, colors and shortening. General timeline edits invoke the configured ADK director. To revise a generated scene, enter `scene scene-1: your new visual prompt` on the current completed short. The new run reuses unaffected music and scenes, rebuilds continuity-dependent scenes, and requires both review gates again. Fixture outputs are synthetic test media; they demonstrate orchestration rather than creative generation quality.

## Repeatable acceptance

With emulators running and no separate worker consuming their queue:

```sh
set -a
source .env.example
set +a
uv run python scripts/studio-smoke.py
```

This fixture-only command creates its own authenticated user/project, obtains a PKCE-bound OAuth token, submits through the official MCP client, checks idempotent replay, processes Pub/Sub messages using fresh runtime instances, records both synthetic fixture review decisions, and verifies the private final download's hash. Output is `.cache/acceptance/studio-final.mp4`. It refuses live provider configuration. Normal app approvals remain human-only.

`npm run test:emulators` starts a fresh suite and runs emulator tests, browser rules tests and this complete export smoke test. Do not run it against ports occupied by another suite. CI installs FFmpeg, JDK and the renderer browser before running the checks.

## Live configuration

Set Firebase public configuration in `apps/web/.env.local` and server configuration in an ignored local env file. Never put service-account credentials or model API keys in `NEXT_PUBLIC_*` variables. Start from `infrastructure/production.env.example`; keep the existing `infrastructure/production.env` private.

Explicit routes:

- `VIBESHORTS_PROVIDER=vertex`: server ADC, real cloud project, model-specific locations and positive reviewed allowances.
- `VIBESHORTS_PROVIDER=developer`: an explicit server `VIBESHORTS_DEVELOPER_API_KEY`, real private Firebase/GCS infrastructure, reviewed allowances and route-specific models.
- `fixture`: demo emulators and deterministic media, without paid model calls.

Model settings include `IMAGE_MODEL`, `VIDEO_MODEL`, `MUSIC_MODEL`, `DIRECTOR_MODEL`, `DEVELOPER_VIDEO_MODEL` and `DEVELOPER_MUSIC_MODEL`, under the `VIBESHORTS_` prefix. There is no automatic model substitution. The baseline image model remains configurable and its deprecated status is exposed.

The JSON rate profile requires the image token rates, `version` and `verified_at`. Before enabling video/music/director/render operations, add positive integer `video_per_second_micros`, `music_per_call_micros`, `director_reservation_micros`, and `render_per_call_micros`. Video reserves eight source seconds conservatively; director, music and render use reviewed per-call ceilings. These charges are estimates until billing reconciliation. Set allowances for the full multi-scene run, not just its first storyboard call.

ADK has its own locked Python environment because its SDK dependency versions differ from the MCP 2.2 environment. Set `VIBESHORTS_ADK_PYTHON` to its interpreter if running outside the repository root. Session events persist in Firestore and bind to the authenticated project/user. Director session/invocation/event correlation is recorded on the job. The Firestore result bridge associates real persisted ADK function-call ids with durable job ids and delivers bounded results once, using delivery leases and deterministic event ids. It is available to asynchronous ADK tool bindings; the current director produces a typed plan and the application scheduler owns its production jobs; application jobs and approvals govern the production scheduler.

For Cloud Run rendering, build `Dockerfile.render`, deploy the disabled/reviewed templates explicitly, set `VIBESHORTS_RENDER_RUNNER=cloud_run` and `VIBESHORTS_RENDER_CLOUD_JOB=projects/PROJECT/locations/REGION/jobs/JOB`. Grant the API identity permission to run that job with overrides. Give the render identity narrowly scoped object read/write permissions; no provider or Firebase administration roles. Set renderer retries to zero. Submission persists an operation handle; recovery polls it instead of launching another execution. A request interrupted before its handle is recorded requires operator reconciliation.

Local Docker rendering uses `VIBESHORTS_RENDER_RUNNER=docker` and `VIBESHORTS_RENDER_IMAGE`. It runs with network disabled, read-only root filesystem, resource limits and a package-only volume. Local direct rendering is allowed only in emulator mode. Packages include a browser content policy that blocks external origins and use only bundled runtime, fonts and media. Cloud renderer containers and their isolation/IAM configuration must be validated in the target environment before production use; Cloud Run alone does not establish the entire isolation contract.

## Scope and remaining validation

Implemented: image/video/music jobs, media preparation/frame extraction, typed storyboards, two review gates, immutable HyperFrames packages, rendering/export, Studio timeline, revisions, dependency traversal, project members, three director policies, locale requests, batch brief submission and deterministic brand checks.

The application schedules job dependencies and approvals durably rather than asking a resident director to wait. neural brand assessment, organization-level shared asset libraries and a template catalog remain extensions to the README roadmap. Locale handling in live plans depends on the director; bundled Inter covers Latin text, so upload an appropriate brand font for other scripts.

Verified locally: unit/transport tests, OAuth/stdio/Inspector image workflows, default-deny rules, ADK session persistence tests, frontend production compilation, and actual fixture video export. Live ADK/Vertex/Developer calls, container builds, production storage signing/IAM and deployed render isolation require credentials and target infrastructure. Browser UI interaction was unavailable in this tool session; frontend interaction still needs your browser test.
