# VibeShorts setup

The image slice and complete fixture short workflow are implemented. See [STUDIO.md](STUDIO.md) for timeline editing, approvals, media routes and export configuration.

## Configuration files

Run the commands in this guide from the repository root.

- **`backend/.env`**: local fixture backend and Firebase emulator settings. `scripts/dev.sh` and `npm run emulators` load it automatically.
- **`backend/.env.production`**: the single active backend configuration for real Firebase/GCP/Vertex services. The API reads exported environment variables; load this file explicitly in its terminal. Production jobs enter through authenticated Pub/Sub push endpoints on the API.
- **`frontend/.env.local`**: Studio browser configuration. Next.js loads it automatically for the web app. Use emulator values for the fixture workflow, or your Firebase web app values for the live workflow.
- **`frontend/.env.production.local`**: optional live browser configuration for production builds and `next start`. It overrides `.env.local` in production; `next dev` continues to use `.env.local`. Create it from `frontend/.env.production.example` and fill the Firebase web app values before using it.
- **`backend/.env.example` and `frontend/.env.example`**: fixture templates.
- **`backend/.env.production.example` and `frontend/.env.production.example`**: production templates. Copy them to `backend/.env.production` and `frontend/.env.production.local` respectively, only when those active files are missing. Examples document defaults and requirements; they are not an additional configuration to maintain.

Production has two active env files: `backend/.env.production` for server configuration
and `frontend/.env.production.local` for browser configuration. There is no separate
infrastructure env file to update. The frontend API URL and Firebase project must match
the backend API URL and application project; `check:integrations` checks this pairing.
Keep these files and `frontend/.env.local` private; store service-account JSON files
outside the repository. Provider keys and Admin private keys belong only on the server,
never in `NEXT_PUBLIC_*` variables.

The files in `infrastructure/` are deployment templates, not an env-file loader. When
deploying, supply the backend configuration to the API service, the public frontend
configuration to the web build, and the project/region/service identities to the
deployment platform. Keep deployment-specific image names and resource sizes in those
templates. Local env files are excluded from Docker images.

Run `npm run check:integrations` to check the local backend/frontend configuration
without network requests. `scripts/dev.sh` runs the same check before starting the apps.
For live files, run:

```sh
npm run check:integrations -- --backend-env backend/.env.production --frontend-env frontend/.env.production.local
```

This checks modes, Firebase project identity, API and emulator addresses, credential
file presence, deployment placeholders and full-short rate ceilings. It does not
verify IAM, deployed services, model access or billing.

## Local setup

Requirements: Python 3.12, `uv` 0.10+, Node **22.19+**, JDK **21**, and FFmpeg. On macOS, install FFmpeg with `brew install ffmpeg`. Use a demo Firebase project for fixture development. On this workspace, project-local Node and Java are available under `.cache`; they do not replace system installations.

```sh
uv sync --project backend --frozen
uv sync --project backend/agents/creative_director --frozen
npm ci
# Create missing files without replacing your existing configuration.
if [ ! -f backend/.env ]; then cp backend/.env.example backend/.env; fi
if [ ! -f frontend/.env.local ]; then cp frontend/.env.example frontend/.env.local; fi
```

For this workflow, `backend/.env` must use `VIBESHORTS_MODE=emulator`, `VIBESHORTS_PROVIDER=fixture`, the demo project and emulator hosts from `backend/.env.example`. The frontend must use `NEXT_PUBLIC_MODE=emulator` and the matching demo configuration from `frontend/.env.example`. If you previously configured the frontend for real Firebase, switch its values back deliberately before testing fixtures; the commands above preserve existing files.

Start each component in a separate terminal:

```sh
# Terminal 1: Auth, Firestore, Storage and Pub/Sub
npm run emulators

# Terminal 2: API and /mcp
set -a
source backend/.env
set +a
uv run --directory backend vibeshorts serve

# Terminal 3: durable queue dispatcher and image worker
set -a
source backend/.env
set +a
uv run --directory backend vibeshorts worker

# Terminal 4: Google sign-in and OAuth consent
npm run dev:web
```

Open **http://127.0.0.1:3000**. Google sign-in uses Firebase's simulated provider popup in emulator mode. Create a project, then connect an MCP client. Use `127.0.0.1` consistently: the default CORS origin is `http://127.0.0.1:3000`.

Click a project card to open `/projects/{project_id}`. The project page shows its brand revision, configured image provider, and paginated private images. **View image** authorizes the download through the API before displaying it; **All projects** returns to the workspace without losing the active sign-in session. Image generation remains available through MCP and REST.

If using the project-local Node installed during implementation, prepend it before npm commands:

```sh
export PATH="$PWD/.cache/node/node_modules/.bin:$PATH"
```

`scripts/emulators.sh` automatically selects the project-local JDK and Node when present. Emulator binaries/configuration stay in `.cache`. Firebase emulators are ephemeral by default. Use Firebase's `--import`/`--export-on-exit` options with an ignored `emulator-data` directory when you need persistence across emulator shutdowns; application process restarts already preserve data in the running emulator.

The local emulator ports are Auth **9099**, Firestore **18080**, Storage **9199** and
Pub/Sub **18085**. Keep `firebase.json`, `backend/.env` and the frontend Firestore
emulator address aligned when changing ports. Ports 8080 and 8085 are left available
for other services.

## MCP connections

Local HTTP endpoint: **http://127.0.0.1:8000/mcp**. For live services, use your configured HTTPS API origin with `/mcp`. Authorization metadata is available at `/.well-known/oauth-authorization-server`; resource metadata is at `/.well-known/oauth-protected-resource/mcp`.

The broker accepts pre-registered public clients with PKCE S256. Defaults:

| Client ID | Registered callback |
| --- | --- |
| `vibeshorts-sdk` | `http://127.0.0.1:8765/callback` |
| `vibeshorts-inspector` | `http://localhost:6274/oauth/callback` |
| `vibeshorts-inspector` | `http://localhost:6274/oauth/callback/debug` |
| `vibeshorts-inspector` | `http://127.0.0.1:6276/oauth/callback` |

Run `npm run inspector`. Select Streamable HTTP, enter the endpoint, and configure the static client ID `vibeshorts-inspector`. Request `vibeshorts:read vibeshorts:generate vibeshorts:cancel` when image submission/cancellation is needed. The consent page shows requested permissions and requires explicit project selection. Default read-only grants cannot submit images.

For the Inspector CLI, use `--client-id vibeshorts-inspector --callback-url http://127.0.0.1:6276/oauth/callback`. `--protocol-era modern` and `--protocol-era legacy` are both supported. Run `node_modules/.bin/mcp-inspector --cli --help` for the installed client's options.

For stdio, obtain a Firebase ID token from your own signed-in session and provide it through the environment, never the tool arguments:

```sh
export VIBESHORTS_STDIO_FIREBASE_ID_TOKEN='<Firebase ID token>'
export VIBESHORTS_STDIO_PROJECTS='<project_id>'
export VIBESHORTS_STDIO_SCOPES='vibeshorts:read,vibeshorts:generate,vibeshorts:cancel'
uv run --directory backend vibeshorts-mcp
```

Stdio runs through the same Firebase, access and project checks. Expired credentials stop new commands. `/mcp` accepts broker access tokens and rejects Firebase ID tokens. The emulator's asset-content API accepts either an authorized broker token or Firebase app credentials.

## First image

Bootstrap project, brand and imported image references through the authenticated REST API or the workspace. Every REST mutation body contains `idempotency_key`. A brand update also contains `expected_version`. Upload initiation returns a server-selected upload URL; upload bytes, then call completion before five minutes expire.

Call the MCP tool:

```json
{
  "project_id": "<project_id>",
  "idempotency_key": "first-image-v1",
  "input": {
    "prompt": "A blue product pedestal with cinematic studio lighting",
    "aspect_ratio": "9:16",
    "reference_artifact_ids": []
  }
}
```

Poll `get_job` with the returned job ID. On `succeeded`, call `get_asset` for an output artifact ID. A queued handle is not an image. In emulator mode the returned download URL requires an Authorization header; in production it is a five-minute object-specific signed URL. `list_assets` returns at most 100 records and an opaque query-bound cursor.

The fixture produces a deterministic PNG and simulates a reservation/settlement of 1,000 micro-USD. It makes no Google model calls. Verified imported fonts can be referenced in brand updates and bundled into composition packages. Colors, exact logos, image references and policy text are supported.

## Tests

```sh
uv run --directory backend ruff check api tools execution providers worker mcp tests
uv run --directory backend ruff format --check api tools execution providers worker mcp tests
uv run --directory backend pytest -q -m 'not emulator and not paid'
npm run check:web
npm run build:web
npm run test:emulators
```

Emulator acceptance covers Firestore transactions, Pub/Sub, Storage, OAuth over both MCP protocol eras, an external stdio process, Inspector over an actual HTTP socket, restart recovery, and browser Security Rules. Run these checks in a fresh terminal using the fixture configuration. Stop the existing emulator suite and `scripts/dev.sh` before `npm run test:emulators`: that command starts its own suite and fixture export workflow. It must not compete with an existing worker or occupied emulator ports. These commands do not validate live providers; use the opt-in procedure below for paid acceptance.

## Recovery and operator commands

```sh
uv run --directory backend vibeshorts inspect-job <project_id> <job_id>
uv run --directory backend vibeshorts sweep
uv run --directory backend vibeshorts reconcile <project_id> <job_id> \
  --amount-micros 0 --operator '<operator identity>' \
  --evidence '<documented provider or billing evidence>'
uv run --directory backend vibeshorts revoke-access <Firebase UID>
```

The operator CLI uses workload/ADC permissions. It is not exposed as a public MCP approval or reconciliation tool. Record a zero charge only with evidence. Reconciliation settles the existing liability and closes the job; purchasing another image requires a new request/key. `submission_unknown` never triggers automatic generation. A stored candidate is recovered instead. Cancellation and access revocation retain liability for already-sent requests.

## Vertex and production

### Create the backend configuration

Create `backend/.env.production` only if it does not already exist:

```sh
if [ ! -f backend/.env.production ]; then
  cp backend/.env.production.example backend/.env.production
fi
```

Edit this backend file and replace all `YOUR_*` placeholders. Use `VIBESHORTS_MODE=production` and `VIBESHORTS_PROVIDER=vertex` for Vertex. Configure the private application bucket, HTTPS API/web origins, internal audience/service identities, model locations, reviewed rate profile and approved allowances. The template starts with zero allowances; paid calls remain blocked until you deliberately configure them. For the explicit Developer API route, use `VIBESHORTS_PROVIDER=developer` and a server-only `VIBESHORTS_DEVELOPER_API_KEY` instead of Vertex credentials.

### Separate Firebase and Vertex projects

`GOOGLE_CLOUD_PROJECT` is the application/Firebase project used for Firebase ID-token
verification, Firestore (including director sessions), the storage client and Pub/Sub.
Set `VIBESHORTS_VERTEX_PROJECT` when Vertex AI runs in a different project. Without
this optional setting, Vertex continues to use `GOOGLE_CLOUD_PROJECT`.

Add these settings to `backend/.env.production` when Firebase and Vertex belong to different projects/accounts:

```sh
GOOGLE_CLOUD_PROJECT=your-firebase-project
GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/firebase-credentials.json
VIBESHORTS_VERTEX_PROJECT=your-vertex-project
VIBESHORTS_VERTEX_CREDENTIALS=/absolute/path/to/vertex-credentials.json
```

`VIBESHORTS_VERTEX_CREDENTIALS` is optional: omit it if the application's ADC identity
has the required access in both projects. Otherwise, it selects a separate Google
credential JSON for Vertex image, video, music and director calls, including retrieval
of Vertex-generated GCS video output. The selected Vertex identity needs access to
that output bucket. Private application artifacts continue to use application ADC
and `VIBESHORTS_BUCKET`; the director's Firestore/brand reads use application ADC too.
Credential contents and paths are not added to provider job snapshots.

Keep the configured application bucket, queue and server Firebase project consistent.
Other production settings remain required; these four settings alone are not a complete
production configuration. This separation is project routing and credential selection,
not automatic cross-project permission provisioning. The application identity needs its
Firebase/Firestore/storage/Pub/Sub permissions; the Vertex identity needs Vertex access,
billing/quota in the AI project, and access to provider output objects.

New Vertex jobs snapshot their AI project. Already accepted jobs without that field
retain the legacy application-project routing rather than switching to the new AI
project on retry. Drain existing work before changing the application project or
credential identities. No automatic cross-project IAM grants or deployment occur.

### Configure the Studio frontend

In `frontend/.env.local`, use the **Firebase project's** web app configuration from
Firebase Console → Project settings → General → Your apps. Its project ID must match
backend `GOOGLE_CLOUD_PROJECT`, not `VIBESHORTS_VERTEX_PROJECT`:

```dotenv
NEXT_PUBLIC_MODE=production
NEXT_PUBLIC_FIREBASE_PROJECT_ID=your-firebase-project
NEXT_PUBLIC_FIREBASE_API_KEY=your-firebase-web-api-key
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=your-firebase-project.firebaseapp.com
NEXT_PUBLIC_API_URL=https://your-api-host
```

Remove `NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_URL` from the live frontend configuration.
Enable Google sign-in in Firebase Authentication and configure the authorized Studio
domain. The Firebase web API key is browser configuration; it is not a Vertex key or
an Admin service-account private key. Never put either credential JSON or its private
key in `NEXT_PUBLIC_*` settings. Restart the frontend after editing the file; deployed
frontend builds must be rebuilt with the intended public configuration.

The Firebase web key is the `apiKey` in Firebase Console → Project settings → General
→ Your apps → Web app configuration. It identifies the browser app's Firebase project
for sign-in; application ADC remains the backend credential. See
[Firebase API keys](https://firebase.google.com/docs/projects/api-keys).

To keep local emulators while building the live frontend, create
`frontend/.env.production.local` from `frontend/.env.production.example` and fill in
the real public Firebase configuration. Keep both emulator variables out of the live
file: `NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_URL` and `NEXT_PUBLIC_FIRESTORE_EMULATOR_HOST`.
Then run the live integration check before `npm run build:web`.

### Test locally with real Firebase and Vertex

Use `VIBESHORTS_MODE=production`, `VIBESHORTS_PROVIDER=vertex` and
`VIBESHORTS_LOCAL_LIVE=1` in `backend/.env.production`. This keeps real authentication,
Firestore, Storage, Pub/Sub and Vertex, while permitting loopback HTTP origins:

```dotenv
VIBESHORTS_PUBLIC_URL=http://127.0.0.1:8000
VIBESHORTS_WEB_URL=http://127.0.0.1:3000
GOOGLE_CLOUD_PROJECT=vibeshorts-fb
VIBESHORTS_VERTEX_PROJECT=vibeshorts-509805
```

In `frontend/.env.production.local`, use the real Firebase web app configuration,
`NEXT_PUBLIC_MODE=production` and `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000`.
Enable Google sign-in and add `127.0.0.1` to Firebase Authentication's authorized
domains for this local test. Use ADC with access to both projects; no separate credential
file is needed when the same identity has both permissions.

Run from the repository root:

```sh
npm run dev:live -- --check
npm run dev:live
```

Stop any previous `npm run dev` or `dev:live` stack with Ctrl+C first. The launcher
checks ports 8000 and 3000 and stops its other services if one exits.

Open **http://127.0.0.1:3000**. The launcher loads the real-service files for both apps,
clears emulator settings and exports the public frontend configuration before starting
`next dev`. It starts a loopback-only API and a local Pub/Sub pull worker using subscription
`vibeshorts-local-live`; the configured topic is `vibeshorts-local-live-jobs`. The worker
creates that topic/subscription if missing and needs the corresponding Pub/Sub permissions.
Local internal HTTP job endpoints are disabled; user requests still require Firebase tokens.
Private asset uploads and downloads use the authenticated local API, so user ADC does
not need a service account capable of signing storage URLs.

Startup checks sign-in and image generation configuration. Image requests use the real
Vertex provider and the configured spend caps. Complete short generation additionally
needs positive video/music/director rate ceilings and a Docker or Cloud Run renderer;
the direct `local` renderer remains exclusive to fixtures. Run the full production
integration check when configuring those features.

Unset `VIBESHORTS_LOCAL_LIVE` (or set it to `0`) before deployment. Without the opt-in,
production continues to require HTTPS and authenticated internal service identities.

### Start deployed production services

Use a fresh API terminal. Clear emulator variables, then load `backend/.env.production`:

```sh
unset FIREBASE_AUTH_EMULATOR_HOST FIRESTORE_EMULATOR_HOST
unset STORAGE_EMULATOR_HOST PUBSUB_EMULATOR_HOST
set -a
source backend/.env.production
set +a
```

In the API terminal:

```sh
uv run --directory backend vibeshorts serve
```

Production jobs run through `/internal/jobs` via authenticated Pub/Sub push. Configure
the subscription and scheduler templates in `infrastructure/`; the `vibeshorts worker`
command is only for local emulators.

In a separate frontend terminal, with `frontend/.env.local` configured above:

```sh
npm run dev:web
```

The development servers still listen locally, but production mode requires HTTPS
public API/web URLs. Use configured HTTPS hosting or a reverse proxy to those local
servers, and keep the browser URL, Firebase authorized domain, API origin and
`VIBESHORTS_WEB_URL` consistent. Setting real credentials does not remove this URL
requirement. Configure a supported Docker or Cloud Run renderer before attempting a
complete live video export; see [Studio rendering](STUDIO.md#rendering-configuration).

Do not use `scripts/dev.sh` or `npm run emulators` for this live workflow: they load
`backend/.env`. The backend does not automatically select `.env.production` from its
filename. Switching server modes needs new processes with the correct environment;
switching frontend modes needs updated `.env.local` and a restart/rebuild.

### Production requirements and acceptance

Production requires real Firebase/Firestore, a private GCS bucket, Pub/Sub, Google sign-in domains, ADC, a positive `VIBESHORTS_PAID_ALLOWANCE_MICROS`, and a reviewed `VIBESHORTS_RATE_JSON`. All emulator variables must be absent. Set public API/web URLs to HTTPS and configure allowed internal service identities. The rate profile has `version`, `verified_at`, `input_per_million_micros`, and `output_per_million_micros`; these are deployment inputs, not fabricated prices.

Provider calls use the accepted job's model, API version and location. The baseline is `gemini-2.5-flash-image`, `v1`, `global`; its deprecated status is exposed by `get_capabilities`. No automatic replacement/fallback is performed. Verify live availability and review current rates before enabling it.

Production allowances are enforced against the per-run cap, the shared project budget, and `budgets/account`. The account allowance covers all projects, so creating another project does not replenish paid capacity. The stored account cap is operator-controlled; lowering the configured allowance also restricts new reservations. Monetary values are integer micro-USD. Usage-derived charges are labeled estimates until reconciled with actual billing.

For opt-in live image acceptance, use a separate terminal, clear emulator variables and load `backend/.env.production` as shown above. Obtain a current Firebase ID token from a user signed into the real **Firebase project** and set `VIBESHORTS_SMOKE_FIREBASE_ID_TOKEN` privately in that terminal. This is not a GCP access token, Vertex key or MCP broker token.

Run `uv run --directory backend vibeshorts preflight-paid` before enabling the smoke test. It reports the application and Vertex project IDs and checks allowances and credential-file presence. This command makes no network calls, reads no credential contents, and reports configuration blockers without printing tokens. A passing preflight does not verify IAM, bucket privacy, billing or model availability.

The template records standard pricing checked on 2026-10-03: $0.30 per million input tokens and $30 per million image output tokens. The current adapter conservatively applies the image rate to text output as well. Its single-image reservation is 71,271 micro-USD ($0.071271); actual charges remain usage estimates pending billing evidence. Review [Google pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing) before authorizing execution. The [model page](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/2-5-flash-image) currently lists March 15, 2027 as the cloud retirement date; no model substitution is configured.

```sh
# After loading the server config, supplying the Firebase token and passing preflight:
VIBESHORTS_RUN_PAID_SMOKE=1 uv run --directory backend pytest -q tests/test_vertex.py -m paid
```

This test can incur charges: it generates one real Vertex image and validates private storage, content hashing and duplicate-execution protection. It does not validate the full director/video/music/render workflow. No paid smoke call runs by default. Deployment is also explicit. Container and Cloud Run/Pub/Sub/Scheduler templates are in `infrastructure`; replace every `YOUR_*` placeholder before applying. Grant the application identity Firestore access, Firebase user-read permissions, scoped bucket object permissions and Pub/Sub publishing; grant the Vertex identity the AI/output access described above. Signed URLs with Cloud Run ADC additionally require IAM `signBlob` permission on the signing service identity. Keep administration/revocation rights on operator identities.

The shared API service verifies OIDC issuer/audience and allowlisted service email on internal routes. Configure the queue push subscription and one-minute scheduler from the templates. `/internal/metrics` reports process-local counters; structured logs and durable jobs/ledger entries provide cross-instance truth. A sweep repairs outbox dispatch if a process dies after acceptance.
