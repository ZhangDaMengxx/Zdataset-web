#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"
if [[ -f "$project_dir/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$project_dir/.env"
  set +a
fi
export PYTHONPATH="$project_dir/backend${PYTHONPATH:+:$PYTHONPATH}"
web_python="${ZDATASET_PYTHON:-${NERO_PYTHON:-python3}}"
exec "$web_python" -m uvicorn app.main:app \
  --host "${ZDATASET_HOST:-${NERO_HOST:-127.0.0.1}}" \
  --port "${ZDATASET_PORT:-${NERO_PORT:-8090}}"
