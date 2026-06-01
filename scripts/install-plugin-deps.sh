#!/usr/bin/env bash
# install-plugin-deps.sh — venv equivalent of the Dockerfile install loop.
#
# Installs every `backend/plugins/<name>/requirements.txt` into the active
# Python environment, passing `backend/requirements.txt` as a pip --constraint
# so shared dep versions cannot drift. Run after the standard
# `pip install -r backend/requirements.txt`.
#
# Idempotent. A plugin missing requirements.txt is silently skipped.
#
# Usage (from repo root, with venv activated):
#     ./scripts/install-plugin-deps.sh
#
# To restrict to a subset of plugins:
#     ./scripts/install-plugin-deps.sh pbpk horizontal_fl

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGINS_DIR="$REPO_ROOT/backend/plugins"
CONSTRAINT="$REPO_ROOT/backend/requirements.txt"

if ! command -v pip >/dev/null 2>&1; then
    echo "error: pip not found on PATH (activate your venv first)" >&2
    exit 1
fi

if [ ! -f "$CONSTRAINT" ]; then
    echo "error: $CONSTRAINT not found" >&2
    exit 1
fi

if [ $# -gt 0 ]; then
    plugins=("$@")
else
    plugins=()
    for d in "$PLUGINS_DIR"/*/; do
        name="$(basename "$d")"
        case "$name" in
            _*|.*) continue ;;
        esac
        plugins+=("$name")
    done
fi

for name in "${plugins[@]}"; do
    req="$PLUGINS_DIR/$name/requirements.txt"
    if [ ! -f "$req" ]; then
        continue
    fi
    echo "==> installing plugin deps: $name"
    pip install --constraint "$CONSTRAINT" -r "$req"
done

echo "Done."
