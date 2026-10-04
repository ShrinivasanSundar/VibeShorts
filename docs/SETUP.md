# VibeShorts setup

The image slice and complete fixture short workflow are implemented. See [STUDIO.md](STUDIO.md) for timeline editing, approvals, media routes and export configuration.

## Local setup

Requirements: Python 3.12, `uv` 0.10+, Node **22.19+**, JDK **21**, and FFmpeg. On macOS, install FFmpeg with `brew install ffmpeg`. Use a demo Firebase project for fixture development. On this workspace, project-local Node and Java are available under `.cache`; they do not replace system installations.

```sh
uv sync --frozen
uv sync --project agents/creative_director --frozen
npm ci
cp .env.example .env
cp apps/web/.env.example apps/web/.env.local
```

Start each component in a separate terminal:

```sh
# Terminal 1: Auth, Firestore, Storage and Pub/Sub
npm run emulators

# Terminal 2: API and /mcp
set -a
source .env
set +a
uv run vibeshorts serve

# Terminal 3: durable queue dispatcher and image worker
set -a
source .env
set +a
uv run vibeshorts worker

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

## MCP connections

HTTP endpoint: **http://127.0.0.1:8000/mcp**. Authorization metadata is available at `/.well-known/oauth-authorization-server`; resource metadata is at `/.well-known/oauth-protected-resource/mcp`.

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
uv run vibeshorts-mcp
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
uv run ruff check apps tools execution providers worker mcp tests
uv run ruff format --check apps tools execution providers worker mcp tests
uv run pytest -q -m 'not emulator and not paid'
npm run check:web
npm run build:web
npm run test:emulators
```

Emulator acceptance covers Firestore transactions, Pub/Sub, Storage, OAuth over both MCP protocol eras, an external stdio process, Inspector over an actual HTTP socket, restart recovery, and browser Security Rules. Emulator tests must run without an already-running suite on the configured ports.

## Recovery and operator commands

```sh
uv run vibeshorts inspect-job <project_id> <job_id>
uv run vibeshorts sweep
uv run vibeshorts reconcile <project_id> <job_id> \
  --amount-micros 0 --operator '<operator identity>' \
  --evidence '<documented provider or billing evidence>'
uv run vibeshorts revoke-access <Firebase UID>
```

The operator CLI uses workload/ADC permissions. It is not exposed as a public MCP approval or reconciliation tool. Record a zero charge only with evidence. Reconciliation settles the existing liability and closes the job; purchasing another image requires a new request/key. `submission_unknown` never triggers automatic generation. A stored candidate is recovered instead. Cancellation and access revocation retain liability for already-sent requests.

## Vertex and production

Production requires real Firebase/Firestore, a private GCS bucket, Pub/Sub, Google sign-in domains, ADC, a positive `VIBESHORTS_PAID_ALLOWANCE_MICROS`, and a reviewed `VIBESHORTS_RATE_JSON`. All emulator variables must be absent. Set public API/web URLs to HTTPS and configure allowed internal service identities. The rate profile has `version`, `verified_at`, `input_per_million_micros`, and `output_per_million_micros`; these are deployment inputs, not fabricated prices.

Provider calls use the accepted job's model, API version and location. The baseline is `gemini-2.5-flash-image`, `v1`, `global`; its deprecated status is exposed by `get_capabilities`. No automatic replacement/fallback is performed. Verify live availability and review current rates before enabling it.

Production allowances are enforced against the per-run cap, the shared project budget, and `budgets/account`. The account allowance covers all projects, so creating another project does not replenish paid capacity. The stored account cap is operator-controlled; lowering the configured allowance also restricts new reservations. Monetary values are integer micro-USD. Usage-derived charges are labeled estimates until reconciled with actual billing.

Opt-in live acceptance:

Start from [production.env.example](../infrastructure/production.env.example) in a separate shell. Its allowances are zero, so paid execution remains disabled. Replace project, bucket, HTTPS origins and internal identity placeholders, configure ADC and a current Firebase credential, and set only the approved allowances. Run `uv run vibeshorts preflight-paid` before enabling the smoke test. This command makes no network calls, reads no credential contents, and reports configuration blockers without printing tokens. A passing preflight does not verify IAM, bucket privacy, billing or model availability.

The template records standard pricing checked on 2026-10-03: $0.30 per million input tokens and $30 per million image output tokens. The current adapter conservatively applies the image rate to text output as well. Its single-image reservation is 71,271 micro-USD ($0.071271); actual charges remain usage estimates pending billing evidence. Review [Google pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing) before authorizing execution. The [model page](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/2-5-flash-image) currently lists March 15, 2027 as the cloud retirement date; no model substitution is configured.

```sh
# Configure Vertex, a real project, rate profile, private storage and ADC first.
export VIBESHORTS_RUN_PAID_SMOKE=1
export VIBESHORTS_SMOKE_FIREBASE_ID_TOKEN='<your own Firebase ID token>'
uv run pytest -q -m paid
```

No paid smoke call runs by default. Deployment is also explicit. Container and Cloud Run/Pub/Sub/Scheduler templates are in `infrastructure`; replace every `YOUR_*` placeholder before applying. Grant runtime Firestore access, Firebase user-read permissions, Vertex access, scoped bucket object permissions and Pub/Sub publishing. Signed URLs with Cloud Run ADC additionally require IAM `signBlob` permission on the signing service identity. Keep administration/revocation rights on operator identities.

The shared API service verifies OIDC issuer/audience and allowlisted service email on internal routes. Configure the queue push subscription and one-minute scheduler from the templates. `/internal/metrics` reports process-local counters; structured logs and durable jobs/ledger entries provide cross-instance truth. A sweep repairs outbox dispatch if a process dies after acceptance.
