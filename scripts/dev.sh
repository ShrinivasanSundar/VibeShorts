#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then cp .env.example .env; fi
if [ ! -f apps/web/.env.local ]; then cp apps/web/.env.example apps/web/.env.local; fi
set -a; source .env; set +a
export VIBESHORTS_RENDER_RUNNER="${VIBESHORTS_RENDER_RUNNER:-local}"
if [ -d .cache/node/node_modules/.bin ]; then export PATH="$PWD/.cache/node/node_modules/.bin:$PATH"; fi
command -v ffmpeg >/dev/null || { echo "Install FFmpeg before starting Studio."; exit 1; }
.venv/bin/vibeshorts serve & api_pid=$!
.venv/bin/vibeshorts worker & worker_pid=$!
npm run dev:web & web_pid=$!
trap 'kill "$api_pid" "$worker_pid" "$web_pid" 2>/dev/null || true' EXIT INT TERM
wait
