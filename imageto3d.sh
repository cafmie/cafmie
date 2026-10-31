#!/usr/bin/env bash
# One entry point: start the local server and open the application window.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="${PYTHON:-python3}"
fi
if [[ -t 1 ]]; then
  exec "$PY" -m imageto3d app "$@"
fi
LOG="${XDG_DATA_HOME:-$HOME/.local/share}/imageto3d"
mkdir -p "$LOG"
exec "$PY" -m imageto3d app "$@" >>"$LOG/app.log" 2>&1
