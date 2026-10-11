#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for file in backend/.env.production frontend/.env.production.local; do
  [ -f "$file" ] || { echo "Missing $file; configure it from its production example."; exit 1; }
done
unset FIREBASE_AUTH_EMULATOR_HOST FIRESTORE_EMULATOR_HOST STORAGE_EMULATOR_HOST
unset PUBSUB_EMULATOR_HOST FIREBASE_STORAGE_EMULATOR_HOST FIREBASE_EMULATOR_HUB
set -a
source backend/.env.production
source frontend/.env.production.local
set +a
export VIBESHORTS_LOCAL_LIVE=1
# Explicit public overrides let next dev use real Firebase despite the fixture .env.local.
export NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_URL=""
export NEXT_PUBLIC_FIRESTORE_EMULATOR_HOST=""
if ! command -v docker >/dev/null 2>&1 && [ -x /usr/local/bin/docker ]; then
  export PATH="/usr/local/bin:$PATH"
fi
if [ -d .cache/node/node_modules/.bin ]; then export PATH="$PWD/.cache/node/node_modules/.bin:$PATH"; fi
backend/.venv/bin/python backend/scripts/check-integrations.py \
  --backend-env backend/.env.production --frontend-env frontend/.env.production.local --image-only
if [ "${VIBESHORTS_RENDER_RUNNER:-}" = docker ]; then
  command -v docker >/dev/null 2>&1 || { echo "Docker is not on PATH."; exit 1; }
  docker info >/dev/null 2>&1 || { echo "Start your existing Docker daemon, then retry."; exit 1; }
  docker image inspect "${VIBESHORTS_RENDER_IMAGE:-vibeshorts-render:local}" >/dev/null 2>&1 || {
    echo "Build the render image: docker build -f infrastructure/Dockerfile.render -t vibeshorts-render:local ."
    exit 1
  }
fi
if [ "${1:-}" = --check ]; then exit 0; fi
exec backend/.venv/bin/python backend/scripts/run-local-live.py
