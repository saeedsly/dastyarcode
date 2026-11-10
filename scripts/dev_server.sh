#!/usr/bin/env bash
# Dev helper: run Dastyar with an isolated data dir (handy in sandboxes)
set -euo pipefail
cd "$(dirname "$0")/.."
export DASTYAR_DATA="${DASTYAR_DATA:-/tmp/dastyar-dev}"
mkdir -p "$DASTYAR_DATA"
echo "data dir: $DASTYAR_DATA"
python3 -m dastyar serve --port "${PORT:-8577}" --no-browser
