# Compatibility and verification

The lockfiles are the authoritative dependency versions. Baseline implementation environment:

| Component | Version / contract |
| --- | --- |
| Python | 3.12.11; project requires 3.12 |
| uv | 0.10.0 |
| MCP Python SDK | 2.2.0; `MCPServer` |
| MCP protocols | 2026-07-28 discovery and 2025-11-25 legacy initialization |
| FastAPI / Pydantic | 0.128.2 / 2.12.5 |
| Firebase Admin | 7.7.0 |
| Google Gen AI | 2.25.0 |
| Firestore / Storage / Pub/Sub Python clients | 2.34.0 / 3.16.0 / 2.42.0 |
| Node / JDK used locally | 22.23.3 / Temurin 21.0.12.1 |
| Next.js / React | 16.3.8 / 19.3.0 |
| Firebase Web / CLI | 12.19.0 / 15.32.1 |
| MCP Inspector | 2.9.0; requires Node >=22.19 |
| ADK / HyperFrames / GSAP | 2.11.0 in an isolated Python environment / 0.8.116 / 3.15.0 |
| Application schema | v1 image and Studio contracts; integer micro-USD |

Python SDK v2 exposes snake_case model attributes while its wire serializer handles protocol field names. MCP tools declare output schemas and provide structured output plus a JSON text block. Explicit tool failures use `is_error=True` in Python (`isError` on the legacy wire).

Fixture operation, protocol, emulator persistence/recovery and rules checks are exercised during implementation. Vertex adapter calls are mocked in automated tests; a live paid call and deployed GCS IAM signing require the opt-in acceptance procedure in [SETUP.md](SETUP.md).

The Node lockfile overrides patched transitive gRPC, OpenTelemetry, FTP and gaxios UUID packages. An audit after these overrides reports no production dependency advisories. Development tooling still inherits the unpatched `braces` 3.0.3 advisory through Firebase CLI's file watcher; do not run its watcher against untrusted pattern inputs. Avoid `npm audit fix --force`, which currently proposes incompatible major downgrades. Recheck advisories when upgrading the CLI.

Container templates were supplied; Docker is not installed in this workspace, so container image builds have not been executed here. CI runs lockfile installs, Python checks, web compilation and emulator acceptance.

## Live local acceptance (2026-10-03)

The running emulator backend completed a remote OAuth fixture workflow through the public HTTP routes: authorization request, authenticated project consent, PKCE code exchange, token refresh, MCP image submission, polling, and authenticated artifact download. The official Python client and MCP Inspector CLI both read the completed job using modern and legacy protocol modes. Identical image submission replay returned the same job identifier. The downloaded PNG matched the immutable artifact SHA-256; revoking the grant made subsequent downloads return HTTP 401. Negative checks also rejected an incorrect PKCE verifier, authorization-code replay, and Firebase ID tokens at `/mcp`.

The Inspector browser UI could not be exercised in this session because the browser tool reported no available browser. This verification used the real local HTTP service and Inspector CLI, not a mocked transport. No paid provider calls or deployment occurred. Local evidence is saved in the ignored `.cache/browser/oauth-live-result.json` and `.cache/browser/remote-oauth-fixture.png`.

The full fixture OAuth/MCP short workflow produced a verified six-second 720×1280 H.264/AAC export at 24 fps. Frontend compilation uses the supported Webpack build flag because Turbopack’s local PostCSS process failed to bind a port in this environment. See [STUDIO.md](STUDIO.md) for live configuration and remaining roadmap extensions.
