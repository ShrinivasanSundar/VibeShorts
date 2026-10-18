#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f backend/.env ]; then set -a; source backend/.env; set +a; fi
export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-demo-vibeshorts}"
export VIBESHORTS_MODE=emulator
export VIBESHORTS_RENDER_RUNNER=local
export VIBESHORTS_BUCKET="${VIBESHORTS_BUCKET:-demo-vibeshorts.appspot.com}"
export FIREBASE_AUTH_EMULATOR_HOST="${FIREBASE_AUTH_EMULATOR_HOST:-127.0.0.1:9099}"
export FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:18080}"
export STORAGE_EMULATOR_HOST="${STORAGE_EMULATOR_HOST:-http://127.0.0.1:9199}"
export PUBSUB_EMULATOR_HOST="${PUBSUB_EMULATOR_HOST:-127.0.0.1:18085}"
export XDG_CACHE_HOME="$PWD/.cache"
export XDG_CONFIG_HOME="$PWD/.cache/config"
export FIREBASE_EMULATORS_PATH="$PWD/.cache/firebase/emulators"
export UV_CACHE_DIR="$PWD/.cache/uv"
if [ -d .cache/jdk/Contents/Home ]; then export JAVA_HOME="$PWD/.cache/jdk/Contents/Home"; fi
if [ -n "${JAVA_HOME:-}" ]; then export PATH="$JAVA_HOME/bin:$PATH"; fi
if [ -d .cache/node/node_modules/.bin ]; then export PATH="$PWD/.cache/node/node_modules/.bin:$PATH"; fi
if [ "${1:-}" = test ]; then
  exec node_modules/.bin/firebase emulators:exec --project "$GOOGLE_CLOUD_PROJECT" --only auth,firestore,storage,pubsub "uv run --directory backend pytest -q -m emulator && npm run test:rules && backend/.venv/bin/python backend/scripts/studio-smoke.py"
fi
exec node_modules/.bin/firebase emulators:start --project "$GOOGLE_CLOUD_PROJECT" --only auth,firestore,storage,pubsub
