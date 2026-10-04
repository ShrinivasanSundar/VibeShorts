# Local verification record

Verified on 4 October 2026, without paid provider calls:

- 60 backend unit/transport tests passed, including exact-revision approvals, selective scene regeneration, immutable packages, cancellation, leases, uncertainty and budgets.
- 6 emulator acceptance tests passed: OAuth across both MCP protocol eras, external stdio, MCP Inspector over HTTP and candidate recovery after a crash.
- 3 Firestore/Storage browser rules tests passed.
- Isolated ADK session and result-bridge checks passed: restart, state scopes, ownership, concurrent-version rejection, duplicate completion, correlated function responses, export and deletion.
- Frontend TypeScript and production Webpack build passed.
- Complete fixture short passed authenticated OAuth and the official MCP client, with Pub/Sub processing, fresh runtime instances, both review gates, idempotent replay and private hash-verified download.
- The resulting MP4 is six seconds, 720×1280, 24 fps, H.264 video and stereo 48 kHz AAC audio. A rendered frame was visually inspected.
- Standalone HyperFrames check passed runtime/layout/motion checks and five contrast checks; a real local render passed. The composition builder subsequently removed the nested title wrapper and bundled its font locally.

The full fixture smoke output is `.cache/acceptance/studio-final.mp4`. Acceptance creates its own synthetic user/project and automatically approves only fixture reviews. No live provider smoke or deployment was performed.

Docker is unavailable here, so container builds and deployed isolation are unverified. Browser surfaces were unavailable to the computer-use tool, so the actual Studio UI still needs browser interaction testing. Live provider responses, quotas, credential/IAM configuration and production URL signing require validation in the configured environment.
