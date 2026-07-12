#!/usr/bin/env bash
# Launch FMS in the DEMO / TEST environment (pre-seeded SQLite, API-push mode).
# Usage:  ./test/run.sh
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
export FMS_ENV_FILE="$DIR/demo.env"
cd "$DIR/.."
echo "FMS demo environment — http://localhost:8002"
echo "Sign in: admin@fms.demo / DemoAdmin!2026"
exec python -m uvicorn backend.main:app --host 127.0.0.1 --port 8002
