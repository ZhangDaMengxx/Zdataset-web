#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if [[ -f "$project_dir/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$project_dir/.env"
  set +a
fi

failures=0
check_dir() {
  local label="$1" path="$2" mode="$3"
  if [[ ! -d "$path" ]]; then
    echo "FAIL  $label: directory not found: $path"
    failures=$((failures + 1))
    return
  fi
  if [[ ! -r "$path" ]]; then
    echo "FAIL  $label: not readable: $path"
    failures=$((failures + 1))
    return
  fi
  if [[ "$mode" == "rw" && ! -w "$path" ]]; then
    echo "FAIL  $label: not writable: $path"
    failures=$((failures + 1))
    return
  fi
  echo "OK    $label: $path"
}

web_python="${ZDATASET_PYTHON:-${NERO_PYTHON:-$project_dir/.venv/bin/python}}"
lerobot_repo="${ZDATASET_LEROBOT_REPO:-${NERO_LEROBOT_REPO:-}}"
lerobot_python="${ZDATASET_LEROBOT_PYTHON:-${NERO_LEROBOT_PYTHON:-}}"
capture_roots="${ZDATASET_CAPTURE_ROOTS:-${NERO_CAPTURE_ROOTS:-}}"
state_dir="${ZDATASET_STATE_DIR:-${NERO_STATE_DIR:-$project_dir/data/state}}"
export_root="${ZDATASET_EXPORT_ROOT:-${NERO_EXPORT_ROOT:-$project_dir/data/exports}}"

if [[ ! -x "$web_python" ]]; then
  echo "FAIL  Web Python is not executable: $web_python"
  failures=$((failures + 1))
elif ! "$web_python" -c 'import fastapi, pydantic, uvicorn' >/dev/null 2>&1; then
  echo "FAIL  Web Python is missing FastAPI dependencies: $web_python"
  failures=$((failures + 1))
else
  echo "OK    Web Python: $web_python"
fi

if [[ -z "$capture_roots" ]]; then
  echo "FAIL  ZDATASET_CAPTURE_ROOTS is empty"
  failures=$((failures + 1))
else
  IFS=':' read -r -a root_list <<< "$capture_roots"
  for root in "${root_list[@]}"; do
    [[ -n "$root" ]] && check_dir "Capture root" "$root" rw
  done
fi

if [[ -z "$lerobot_repo" ]]; then
  echo "FAIL  ZDATASET_LEROBOT_REPO is empty"
  failures=$((failures + 1))
else
  check_dir "VLA-HandArm repository" "$lerobot_repo" ro
  for script in build_canonical.py derive_embodiment.py measure_acceptance.py verify_dataset.py; do
    if [[ ! -f "$lerobot_repo/src/lerobot_v3/$script" ]]; then
      echo "FAIL  Missing processing script: $lerobot_repo/src/lerobot_v3/$script"
      failures=$((failures + 1))
    fi
  done
fi

if [[ -z "$lerobot_python" || ! -x "$lerobot_python" ]]; then
  echo "FAIL  LeRobot Python is not executable: ${lerobot_python:-<empty>}"
  failures=$((failures + 1))
else
  echo "OK    LeRobot Python: $lerobot_python"
fi

check_dir "State directory" "$state_dir" rw
check_dir "Export directory" "$export_root" rw

if (( failures > 0 )); then
  echo "Server check failed: $failures problem(s)"
  exit 1
fi

echo "Server check passed"
