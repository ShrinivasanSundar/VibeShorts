#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f backend/.env ]; then cp backend/.env.example backend/.env; fi
if [ ! -f frontend/.env.local ]; then cp frontend/.env.example frontend/.env.local; fi
set -a; source backend/.env; set +a
backend/.venv/bin/python backend/scripts/check-integrations.py
export VIBESHORTS_RENDER_RUNNER="${VIBESHORTS_RENDER_RUNNER:-local}"
if [ -d .cache/node/node_modules/.bin ]; then export PATH="$PWD/.cache/node/node_modules/.bin:$PATH"; fi
command -v ffmpeg >/dev/null || { echo "Install FFmpeg before starting Studio."; exit 1; }
backend/.venv/bin/vibeshorts serve & api_pid=$!
backend/.venv/bin/vibeshorts worker & worker_pid=$!
npm run dev:web & web_pid=$!
trap 'kill "$api_pid" "$worker_pid" "$web_pid" 2>/dev/null || true' EXIT INT TERM
wait
