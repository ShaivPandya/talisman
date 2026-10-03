#!/usr/bin/env bash
# Build the Longaeva submission ZIP (LON-24).
# Compatible with macOS /bin/bash 3.2.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE="${COMPOSE:-docker compose}"
OUTPUT=""

usage() {
  echo "Usage: $0 [--output PATH]"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --output)
      OUTPUT="${2:?--output requires a path}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 2
fi

if [ -z "$OUTPUT" ]; then
  utc="$(date -u +%Y%m%dT%H%M%SZ)"
  sha="unknown"
  dirty=""
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    sha="$(git rev-parse --short=7 HEAD)"
    if [ -n "$(git status --porcelain -- .)" ]; then
      dirty="-dirty"
    fi
  fi
  OUTPUT="$ROOT/dist/longaeva-export-${utc}-${sha}${dirty}.zip"
fi

case "$OUTPUT" in
  /*) ;;
  *) OUTPUT="$PWD/$OUTPUT" ;;
esac

OUTDIR="$(dirname "$OUTPUT")"
OUTBASE="$(basename "$OUTPUT")"
mkdir -p "$OUTDIR"

forbid_file=""
cleanup() {
  if [ -n "${forbid_file}" ] && [ -f "${forbid_file}" ]; then
    rm -f "${forbid_file}"
  fi
}
trap cleanup EXIT

forbid_file="$(mktemp /tmp/longaeva-forbid.XXXXXX)"
chmod 600 "$forbid_file"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  name="$(git config --get user.name || true)"
  email="$(git config --get user.email || true)"
  if [ ${#name} -ge 4 ]; then
    printf '%s\n' "$name" >> "$forbid_file"
  fi
  if [ ${#email} -ge 4 ]; then
    printf '%s\n' "$email" >> "$forbid_file"
  fi
fi

$COMPOSE build api

run_opts=(
  run --rm --no-deps
  --user "$(id -u):$(id -g)"
  -v "$ROOT:/srv/longaeva-src:ro"
  -v "$OUTDIR:/out"
  -e "PYTHONPATH=/srv/longaeva-src/backend"
  -e "LONGAEVA_GUARD_ROOT=/srv/longaeva-src"
  -e "HOME=/tmp"
)

cli_opts=(
  python -m longaeva_app.cli export-zip
  --root /srv/longaeva-src
  --output "/out/$OUTBASE"
)

if [ -s "$forbid_file" ]; then
  run_opts+=(-v "$forbid_file:/forbid:ro")
  cli_opts+=(--forbid-file /forbid)
fi

$COMPOSE "${run_opts[@]}" api "${cli_opts[@]}"

if command -v sha256sum >/dev/null 2>&1; then
  (cd "$OUTDIR" && sha256sum "$OUTBASE" > "$OUTBASE.sha256")
else
  (cd "$OUTDIR" && shasum -a 256 "$OUTBASE" > "$OUTBASE.sha256")
fi

echo "Wrote $OUTPUT"
echo "Wrote $OUTPUT.sha256"
