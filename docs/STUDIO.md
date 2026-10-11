# Studio and complete fixture workflow

VibeShorts now includes the MCP service, REST API, durable execution, Firebase identity/OAuth, and a Next.js Studio. The fixture workflow runs without model credentials and exports an actual HyperFrames MP4. Live adapters are configurable, but their calls and deployment have not been exercised with your credentials.

## Choose your configuration

Run commands from the repository root. Use `backend/.env` for the fixture/emulator backend,
`backend/.env.production` for the real-service backend, and `frontend/.env.local` for the
Studio frontend in either mode. Next.js loads the frontend file automatically; the
backend production file must be explicitly loaded into each API/worker terminal.
Production browser settings live in `frontend/.env.production.local` for builds and
`next start`. The two production templates are `backend/.env.production.example` and
`frontend/.env.production.example`. There is no third infrastructure env file to maintain.

The sections below separate fixture usage from live services. See the
[configuration file guide](SETUP.md#configuration-files) for the full loading rules.
`npm run check:integrations` checks the local pairing without cloud requests. Use
`frontend/.env.production.example` as the template for the live build's
`frontend/.env.production.local`; the setup guide includes the live check command.

## Start locally

Install Python 3.12, uv, Node 22.19+, JDK 21 and FFmpeg. See [SETUP.md](SETUP.md) for Java setup, Firebase configuration and OAuth clients.

```sh
uv sync --project backend --frozen
uv sync --project backend/agents/creative_director --frozen
npm ci
# Preserve existing configuration; create only missing files.
if [ ! -f backend/.env ]; then cp backend/.env.example backend/.env; fi
if [ ! -f frontend/.env.local ]; then cp frontend/.env.example frontend/.env.local; fi
npm run emulators
```

Before starting, confirm `backend/.env` contains the demo fixture/emulator settings and
`frontend/.env.local` uses `NEXT_PUBLIC_MODE=emulator` with the matching demo Firebase
configuration. Existing real-service settings are preserved by the commands above;
switch frontend values deliberately if returning from a live setup.

In another terminal, run `bash scripts/dev.sh`. This starts API/MCP on port 8000, the queue worker and Studio on port 3000. It creates missing local env files without replacing existing files. Open **http://127.0.0.1:3000**. Google sign-in uses the Firebase Auth emulator in this configuration. Keep all emulator services running while using Studio.

After signing in, create a project. Enter a brief in the Director panel and generate a short. Review the storyboard before production starts. Follow progress in Activity; review the completed preview before approving final export. Download the private MP4 and editable ZIP in Exports.

Assets supports verified image, audio, MP4 and font imports. Image uploads have a 7 MB limit, fonts 2 MB and audio/video 200 MB, with a maximum supported media duration of 125 seconds. Brand settings persist immutable revisions with exact logo/font references, colors, image references and policy text.

The timeline supports positioning, trim points, duration, track placement, exact copy, volume/fades, visibility, deletion, zoom, seeking and undo/redo. Save creates a new immutable package using the expected current head. A competing save conflicts. Final export requires approval of the exact current package. Pending local edits must be saved first.

Fixture natural-language edits support quoted copy replacement, title, mute, aspect ratio, colors and shortening. General timeline edits invoke the configured ADK director. To revise a generated scene, enter `scene scene-1: your new visual prompt` on the current completed short. The new run reuses unaffected music and scenes, rebuilds continuity-dependent scenes, and requires both review gates again. Fixture outputs are synthetic test media; they demonstrate orchestration rather than creative generation quality.

## Repeatable acceptance

In a fresh fixture-configured terminal, with emulators running and no separate worker
consuming their queue (do not leave `scripts/dev.sh` running during this smoke test):

```sh
set -a
source backend/.env.example
set +a
uv run --directory backend python scripts/studio-smoke.py
```

This fixture-only command creates its own authenticated user/project, obtains a PKCE-bound OAuth token, submits through the official MCP client, checks idempotent replay, processes Pub/Sub messages using fresh runtime instances, records both synthetic fixture review decisions, and verifies the private final download's hash. Output is `.cache/acceptance/studio-final.mp4`. It refuses live provider configuration. Normal app approvals remain human-only.

Alternatively, stop existing emulators and `scripts/dev.sh`, then run `npm run test:emulators`. It starts its own suite and runs emulator tests, browser rules tests and this complete export smoke test. Do not run it against ports occupied by another suite. Keep `backend/.env` configured for fixtures. These checks do not exercise paid providers. CI installs FFmpeg, JDK and the renderer browser before running the checks.

## Live configuration

### Configure the backend and frontend

Use the ignored `backend/.env.production` as the single backend production configuration.
Create it from `backend/.env.production.example` only when it is missing, then
replace all placeholders and configure reviewed allowances and rates. Keep `backend/.env`
for fixtures; do not copy real credentials into the emulator file.

For separate Firebase and Vertex projects, add to `backend/.env.production`:

```dotenv
GOOGLE_CLOUD_PROJECT=your-firebase-project
GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/firebase-credentials.json
VIBESHORTS_VERTEX_PROJECT=your-vertex-project
VIBESHORTS_VERTEX_CREDENTIALS=/absolute/path/to/vertex-credentials.json
```

The Vertex credential file is optional if application ADC has access to both projects.
Firebase authentication, Firestore/brand/session data, private artifacts and queues
continue to use the application project/credentials. Vertex image/video/music/director
calls use the AI project/credentials. See [split-project setup](SETUP.md#separate-firebase-and-vertex-projects).

In `frontend/.env.local`, use `NEXT_PUBLIC_MODE=production`, the **Firebase project's**
web API key/project ID/auth domain, and the HTTPS API URL. Remove the frontend auth
emulator URL and restart/rebuild Studio. Enable Firebase Google sign-in and authorize
the Studio domain. Never put Admin or provider credentials in `NEXT_PUBLIC_*` variables.
See [frontend configuration](SETUP.md#configure-the-studio-frontend) for the complete example.

### Start and validate live services

For localhost testing with real Firebase and Vertex, use `npm run dev:live` after
configuring `VIBESHORTS_LOCAL_LIVE=1` and the real-service env files. See
[local real-service setup](SETUP.md#test-locally-with-real-firebase-and-vertex).
That launcher uses a local pull worker; a deployed push subscription is not needed.
The instructions below are for deployed production with the local opt-in disabled.

In a fresh API terminal, clear emulator variables and load the backend file:

```sh
unset FIREBASE_AUTH_EMULATOR_HOST FIRESTORE_EMULATOR_HOST
unset STORAGE_EMULATOR_HOST PUBSUB_EMULATOR_HOST
set -a
source backend/.env.production
set +a
```

Run `uv run --directory backend vibeshorts serve` in the API terminal. Production jobs
use the authenticated Pub/Sub push route `/internal/jobs` and the configured scheduler;
the `vibeshorts worker` command is only for emulators. Start `npm run dev:web` separately
with `frontend/.env.local` configured for live development. For production builds,
use the live settings in `frontend/.env.production.local` instead.
Use HTTPS hosting or a reverse proxy matching the configured API/web origins; production
mode requires HTTPS public URLs even when development processes listen locally.
Do not launch `scripts/dev.sh` or emulators for this workflow: those load `backend/.env`.
See [live startup](SETUP.md#start-deployed-production-services) for the terminal sequence.

Before enabling the paid image smoke test, provide a real Firebase user ID token and
run `uv run --directory backend vibeshorts preflight-paid` in the loaded server environment. Preflight is
offline; paid acceptance is explicitly opt-in and can incur charges. See
[production acceptance](SETUP.md#production-requirements-and-acceptance).
Complete short generation additionally needs video/music/director/render budgets and
a configured production renderer. After configuring them, use the same human
storyboard → preview → export review flow described above.

### Provider routes and operation budgets

Explicit routes:

- `VIBESHORTS_PROVIDER=vertex`: server ADC, real cloud project, model-specific locations and positive reviewed allowances.
- `VIBESHORTS_PROVIDER=developer`: an explicit server `VIBESHORTS_DEVELOPER_API_KEY`, real private Firebase/GCS infrastructure, reviewed allowances and route-specific models.
- `fixture`: demo emulators and deterministic media, without paid model calls.

Model settings include `IMAGE_MODEL`, `VIDEO_MODEL`, `MUSIC_MODEL`, `DIRECTOR_MODEL`, `DEVELOPER_VIDEO_MODEL` and `DEVELOPER_MUSIC_MODEL`, under the `VIBESHORTS_` prefix. There is no automatic model substitution. The baseline image model remains configurable and its deprecated status is exposed.

The JSON rate profile requires the image token rates, `version` and `verified_at`. Before enabling video/music/director/render operations, add positive integer `video_per_second_micros`, `music_per_call_micros`, `director_reservation_micros`, and `render_per_call_micros`. Video reserves eight source seconds conservatively; director, music and render use reviewed per-call ceilings. These charges are estimates until billing reconciliation. Set allowances for the full multi-scene run, not just its first storyboard call.

ADK has its own locked Python environment because its SDK dependency versions differ from the MCP 2.2 environment. Set `VIBESHORTS_ADK_PYTHON` to override its interpreter; the default resolves from the backend directory. Session events persist in Firestore and bind to the authenticated project/user. Director session/invocation/event correlation is recorded on the job. The Firestore result bridge associates real persisted ADK function-call ids with durable job ids and delivers bounded results once, using delivery leases and deterministic event ids. It is available to asynchronous ADK tool bindings; the current director produces a typed plan and the application scheduler owns its production jobs; application jobs and approvals govern the production scheduler.

### Rendering configuration

For local live testing with an existing Docker daemon, build the render image from
the repository root:

```sh
docker build -f infrastructure/Dockerfile.render -t vibeshorts-render:local .
```

Set `VIBESHORTS_RENDER_RUNNER=docker` in `backend/.env.production` and restart
`npm run dev:live`. The launcher checks the daemon and image before starting.
On Apple Silicon the image installs native Debian Chromium; other platforms use
the HyperFrames browser download. The render container receives no cloud credentials.

For a small live budget, `VIBESHORTS_VIDEO_MODEL=veo-3.1-lite-generate-001` and
`VIBESHORTS_VIDEO_GENERATE_AUDIO=false` produce silent scene clips with the separate
music track. Configure reviewed model-specific `video_rates` in `VIBESHORTS_RATE_JSON`
for the resolution/audio combinations you enable. Clip reservations use requested
source duration; the shortest source is four seconds even for shorter editorial scenes.

For Cloud Run rendering, build `infrastructure/Dockerfile.render`, deploy the disabled/reviewed templates explicitly, set `VIBESHORTS_RENDER_RUNNER=cloud_run` and `VIBESHORTS_RENDER_CLOUD_JOB=projects/PROJECT/locations/REGION/jobs/JOB` in `backend/.env.production`. Grant the API identity permission to run that job with overrides. Give the render identity narrowly scoped object read/write permissions; no provider or Firebase administration roles. Set renderer retries to zero. Submission persists an operation handle; recovery polls it instead of launching another execution. A request interrupted before its handle is recorded requires operator reconciliation.

Local Docker rendering uses `VIBESHORTS_RENDER_RUNNER=docker` and `VIBESHORTS_RENDER_IMAGE`. It runs with network disabled, read-only root filesystem, resource limits and a package-only volume. Local direct rendering is allowed only in emulator mode. Packages include a browser content policy that blocks external origins and use only bundled runtime, fonts and media. Cloud renderer containers and their isolation/IAM configuration must be validated in the target environment before production use; Cloud Run alone does not establish the entire isolation contract.

## Scope and remaining validation

Implemented: image/video/music jobs, media preparation/frame extraction, typed storyboards, two review gates, immutable HyperFrames packages, rendering/export, Studio timeline, revisions, dependency traversal, project members, three director policies, locale requests, batch brief submission and deterministic brand checks.

The application schedules job dependencies and approvals durably rather than asking a resident director to wait. Neural brand assessment, organization-level shared asset libraries and a template catalog remain extensions to the README roadmap. Locale handling in live plans depends on the director; bundled Inter covers Latin text, so upload an appropriate brand font for other scripts.

Verified locally: unit/transport tests, OAuth/stdio/Inspector image workflows, default-deny rules, ADK session persistence tests, frontend production compilation, and actual fixture video export. Live ADK/Vertex/Developer calls, container builds, production storage signing/IAM and deployed render isolation require credentials and target infrastructure. Browser UI interaction was unavailable in this tool session; frontend interaction still needs your browser test.
