#!/usr/bin/env bash
# Unpack a Longaeva submission ZIP in /tmp and validate it (LON-24 / PR-06).
# Compatible with macOS /bin/bash 3.2.
set -euo pipefail

ZIP=""
LOG=""
NO_CACHE=0
KEEP=0
SKIP_TESTS=0
API_PORT="${API_PORT:-18000}"
WEB_PORT="${WEB_PORT:-13000}"
DB_PORT="${DB_PORT:-15432}"

usage() {
  echo "Usage: $0 --zip PATH [--log PATH] [--no-cache] [--keep] [--skip-tests]"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --zip)
      ZIP="${2:?}"
      shift 2
      ;;
    --log)
      LOG="${2:?}"
      shift 2
      ;;
    --no-cache)
      NO_CACHE=1
      shift
      ;;
    --keep)
      KEEP=1
      shift
      ;;
    --skip-tests)
      SKIP_TESTS=1
      shift
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

if [ -z "$ZIP" ]; then
  echo "--zip is required" >&2
  usage >&2
  exit 2
fi

case "$ZIP" in
  /*) ;;
  *) ZIP="$PWD/$ZIP" ;;
esac

if [ ! -f "$ZIP" ]; then
  echo "ZIP not found: $ZIP" >&2
  exit 2
fi

if [ -z "$LOG" ]; then
  LOG="${ZIP%.zip}-verify.md"
fi

STARTED_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
VERIFY_ID="$(python3 -c 'import secrets; print(secrets.token_hex(3))')"
PROJECT="longaeva-verify-${VERIFY_ID}"
WORK="$(mktemp -d /tmp/longaeva-verify.XXXXXX)"
PKG="$WORK/longaeva"
STEPS="$(mktemp "$WORK/steps.XXXXXX")"
EXCERPTS="$(mktemp "$WORK/excerpts.XXXXXX")"
FAILED=0
FAILED_STEP=""
STEP_NAME=""
STEP_START=0
RAN_COMPOSE=0
FINAL_STATUS="PASS"
KEEP_NOTE=""

redact() {
  python3 -c 'import os,sys; sys.stdout.write(sys.stdin.read().replace(os.environ.get("HOME",""), "~"))'
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

json_field() {
  python3 -c '
import json, sys
raw = sys.stdin.read()
start = raw.find("{")
end = raw.rfind("}")
if start < 0 or end < 0:
    raise SystemExit("no JSON object in input")
cur = json.loads(raw[start:end + 1])
for part in sys.argv[1].split("."):
    if isinstance(cur, dict):
        cur = cur[part]
    else:
        raise SystemExit("not an object")
print(cur)
' "$1"
}

json_len() {
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d) if hasattr(d,"__len__") else 0)'
}

port_in_use() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else
    return 1
  fi
}

begin_step() {
  STEP_NAME="$1"
  STEP_START="$(date +%s)"
  echo "==> $STEP_NAME" >&2
}

end_step() {
  status="$1"
  evidence="$2"
  now="$(date +%s)"
  dur=$((now - STEP_START))
  printf '%s|%s|%s|%s\n' "$STEP_NAME" "$status" "$dur" "$evidence" >> "$STEPS"
  echo "    $status ${dur}s  $evidence" >&2
  if [ "$status" != "PASS" ]; then
    FAILED=1
    FAILED_STEP="$STEP_NAME"
    FINAL_STATUS="FAIL"
    return 1
  fi
}

make_in() {
  make -C "$PKG" \
    PROJECT="$PROJECT" \
    COMPOSE_PROJECT_NAME="$PROJECT" \
    DB_PORT="$DB_PORT" \
    API_PORT="$API_PORT" \
    WEB_PORT="$WEB_PORT" \
    "$@"
}

write_log() {
  mkdir -p "$(dirname "$LOG")"
  zip_bytes="$(wc -c < "$ZIP" | tr -d ' ')"
  zip_sha="$(sha256_file "$ZIP")"
  {
    echo "# Early export rehearsal"
    echo
    echo "- Started (UTC): $STARTED_UTC"
    echo "- Finished (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "- Result: **$FINAL_STATUS**"
    if [ -n "$FAILED_STEP" ]; then
      echo "- Failed step: $FAILED_STEP"
    fi
    echo "- ZIP: \`$(basename "$ZIP")\`"
    echo "- SHA-256: \`$zip_sha\`"
    echo "- ZIP bytes: $zip_bytes"
    echo "- Docker: \`$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo unknown)\`"
    echo "- Compose: \`$(docker compose version --short 2>/dev/null || docker compose version 2>/dev/null | head -n 1)\`"
    echo "- Host: \`$(uname -srm)\`"
    echo "- Compose project: \`$PROJECT\`"
    echo "- Ports: API=$API_PORT WEB=$WEB_PORT DB=$DB_PORT"
    echo "- Work dir: \`$(printf '%s' "$WORK" | redact)\`"
    if [ "$KEEP" -eq 1 ]; then
      echo "- Keep: yes (stack and temp dir left in place)"
    else
      echo "- Keep: no (stack and temp dir removed)"
    fi
    echo
    echo "## Steps"
    echo
    echo "| Step | Result | Seconds | Evidence |"
    echo "| --- | --- | ---: | --- |"
    while IFS='|' read -r name status seconds evidence; do
      echo "| $name | $status | $seconds | $evidence |"
    done < "$STEPS"
    echo
    echo "## Excerpts"
    echo
    if [ -s "$EXCERPTS" ]; then
      cat "$EXCERPTS"
    else
      echo "_No extra excerpts._"
    fi
    echo
    echo "## Notes"
    echo
    echo "- Developer stack on ports 8000/3000/55432 is not used."
    echo "- Browser UF-01/UF-03 flows are not automated here (LON-34 / LON-36)."
    echo "- Replay is expected to be \`exact_match\` inside Compose (same BLAS)."
    if [ -n "$KEEP_NOTE" ]; then
      echo "- $KEEP_NOTE"
    fi
  } > "$LOG"
  echo "Wrote log $LOG" >&2
}

teardown() {
  if [ "$KEEP" -eq 1 ]; then
    KEEP_NOTE="Left $PROJECT and $(printf '%s' "$WORK" | redact) in place (--keep)."
    echo "$KEEP_NOTE" >&2
    return 0
  fi
  if [ "$RAN_COMPOSE" -eq 1 ] && [ -d "$PKG" ]; then
    (cd "$PKG" && COMPOSE_PROJECT_NAME="$PROJECT" DB_PORT="$DB_PORT" API_PORT="$API_PORT" WEB_PORT="$WEB_PORT" \
      docker compose down -v --rmi local --remove-orphans) >/dev/null 2>&1 || true
  fi
  docker rmi "${PROJECT}-web-check" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}

on_exit() {
  code="$?"
  if [ "$code" -ne 0 ]; then
    FINAL_STATUS="FAIL"
    FAILED=1
  fi
  write_log || true
  teardown || true
  if [ "$FAILED" -ne 0 ] && [ "$code" -eq 0 ]; then
    exit 1
  fi
  exit "$code"
}

trap on_exit EXIT

# --- 1. Preflight ---
begin_step "preflight"
for tool in docker git unzip curl python3 make; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "missing tool: $tool" >&2
    end_step FAIL "missing $tool"
    exit 1
  fi
done
docker compose version >/dev/null
if git -C "$WORK" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "temp dir is inside a git work tree" >&2
  end_step FAIL "temp dir inside git work tree"
  exit 1
fi
for port in "$API_PORT" "$WEB_PORT" "$DB_PORT"; do
  if port_in_use "$port"; then
    echo "port $port is already in use" >&2
    end_step FAIL "port $port in use"
    exit 1
  fi
done
sidecar="$ZIP.sha256"
if [ ! -f "$sidecar" ]; then
  echo "checksum sidecar missing: $sidecar" >&2
  end_step FAIL "missing .sha256 sidecar"
  exit 1
fi
expected="$(awk '{print $1}' "$sidecar")"
actual="$(sha256_file "$ZIP")"
if [ "$expected" != "$actual" ]; then
  echo "checksum mismatch" >&2
  end_step FAIL "sha256 mismatch"
  exit 1
fi
end_step PASS "tools, ports $API_PORT/$WEB_PORT/$DB_PORT, sha256 match"

# --- 2. Unpack and inspect ZIP ---
begin_step "unpack"
if ! unzip -q "$ZIP" -d "$WORK"; then
  end_step FAIL "unzip"
  exit 1
fi
if [ ! -d "$PKG" ] || [ ! -f "$PKG/Makefile" ] || [ ! -f "$PKG/docker-compose.yml" ]; then
  end_step FAIL "expected $PKG with Makefile"
  exit 1
fi
listing="$(unzip -Z1 "$ZIP")"
if printf '%s\n' "$listing" | grep -qE '(^|/)\.git(/|$)'; then
  end_step FAIL "ZIP listing contains .git"
  exit 1
fi
if printf '%s\n' "$listing" | python3 -c '
import sys
bad = []
for raw in sys.stdin:
    name = raw.strip()
    base = name.rsplit("/", 1)[-1]
    if base == ".env" or (base.startswith(".env.") and base != ".env.example"):
        bad.append(name)
if bad:
    raise SystemExit("env members: " + ", ".join(bad))
'; then
  true
else
  end_step FAIL "ZIP contains a .env member"
  exit 1
fi
if printf '%s\n' "$listing" | grep -qE '(^|/)node_modules(/|$)'; then
  end_step FAIL "ZIP listing contains node_modules"
  exit 1
fi
if printf '%s\n' "$listing" | grep -qvE '^longaeva/'; then
  end_step FAIL "ZIP entry outside longaeva/"
  exit 1
fi
entry_count="$(printf '%s\n' "$listing" | grep -c . | tr -d ' ')"
if python3 -c '
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
pat = re.compile(rb"(?:/Users|/home)/[A-Za-z0-9._-]+")
hits = []
for path in root.rglob("*"):
    if not path.is_file():
        continue
    if ".git" in path.parts:
        continue
    data = path.read_bytes()
    if pat.search(data):
        hits.append(str(path.relative_to(root)))
if hits:
    print("\n".join(hits))
    raise SystemExit(1)
' "$PKG"; then
  true
else
  end_step FAIL "developer home path in unpacked files"
  exit 1
fi
for rel in scripts/export_submission.sh scripts/verify_export.sh backend/scripts/check.sh; do
  if [ ! -x "$PKG/$rel" ]; then
    end_step FAIL "$rel is not executable"
    exit 1
  fi
done
end_step PASS "$entry_count entries under longaeva/; exec bits present"

# --- 3. Build + strict guard ---
begin_step "guard"
export COMPOSE_PROJECT_NAME="$PROJECT"
export DB_PORT API_PORT WEB_PORT
RAN_COMPOSE=1
build_args=""
web_args=""
if [ "$NO_CACHE" -eq 1 ]; then
  build_args="--no-cache"
  web_args="--no-cache"
fi
if ! out="$(make_in COMPOSE_BUILD_ARGS=$build_args build 2>&1)"; then
  printf '\n### image build (failed)\n\n```\n%s\n```\n' "$(printf '%s\n' "$out" | redact)" >> "$EXCERPTS"
  end_step FAIL "compose build"
  exit 1
fi
if ! out="$(make_in GUARD_ARGS=--strict guard 2>&1)"; then
  printf '\n### isolation guard --strict (failed)\n\n```\n%s\n```\n' "$(printf '%s\n' "$out" | redact)" >> "$EXCERPTS"
  end_step FAIL "isolation guard --strict"
  exit 1
fi
if ! printf '%s\n' "$out" | grep -q "0 findings"; then
  printf '\n### isolation guard --strict\n\n```\n%s\n```\n' "$(printf '%s\n' "$out" | redact)" >> "$EXCERPTS"
  end_step FAIL "guard did not report 0 findings"
  exit 1
fi
end_step PASS "isolation guard --strict: 0 findings"

# --- 4. Fresh git init ---
begin_step "git-init"
(
  cd "$PKG"
  export GIT_CONFIG_GLOBAL=/dev/null
  export GIT_CONFIG_NOSYSTEM=1
  git init -b main >/dev/null
  git add -A
  git -c user.name="Longaeva Export" -c user.email="export@example.invalid" commit -m "Initial import from export ZIP" >/dev/null
)
tracked="$(git -C "$PKG" ls-files | wc -l | tr -d ' ')"
unpacked="$(find "$PKG" -type f ! -path "$PKG/.git/*" | wc -l | tr -d ' ')"
if [ "$tracked" != "$unpacked" ]; then
  end_step FAIL "tracked=$tracked unpacked=$unpacked"
  exit 1
fi
end_step PASS "fresh git init; $tracked files tracked"

# --- 5. Test suite ---
begin_step "tests"
if [ "$SKIP_TESTS" -eq 1 ]; then
  end_step PASS "skipped (--skip-tests)"
else
  if ! out="$(make_in COMPOSE_BUILD_ARGS=$build_args WEB_CHECK_BUILD_ARGS=$web_args check 2>&1)"; then
    printf '\n### make check (failed)\n\n```\n%s\n```\n' "$(printf '%s\n' "$out" | tail -n 80 | redact)" >> "$EXCERPTS"
    end_step FAIL "make check"
    exit 1
  fi
  printf '\n### make check (tail)\n\n```\n%s\n```\n' "$(printf '%s\n' "$out" | tail -n 20 | redact)" >> "$EXCERPTS"
  end_step PASS "make check (ruff, mypy, pytest, frontend)"
fi

# --- 6. Startup ---
begin_step "startup"
if ! out="$(make_in up 2>&1)"; then
  printf '\n### make up (failed)\n\n```\n%s\n```\n' "$(printf '%s\n' "$out" | redact)" >> "$EXCERPTS"
  end_step FAIL "make up"
  exit 1
fi
end_step PASS "make up; api/worker/web/db healthy"

# --- 7. Smoke ---
begin_step "smoke"
if ! curl -sf --max-time 10 "http://127.0.0.1:${API_PORT}/health" >/dev/null; then
  end_step FAIL "GET /health"
  exit 1
fi
if ! curl -sf --max-time 10 "http://127.0.0.1:${API_PORT}/openapi.json" >/dev/null; then
  end_step FAIL "GET /openapi.json"
  exit 1
fi
if ! curl -sf --max-time 10 "http://127.0.0.1:${API_PORT}/runs" >/dev/null; then
  end_step FAIL "GET /runs"
  exit 1
fi
if ! curl -sf --max-time 10 "http://127.0.0.1:${WEB_PORT}/" >/dev/null; then
  end_step FAIL "GET web /"
  exit 1
fi
if ! curl -sf --max-time 10 "http://127.0.0.1:${WEB_PORT}/runs" >/dev/null; then
  end_step FAIL "GET web /runs"
  exit 1
fi
if ! curl -sf --max-time 10 "http://127.0.0.1:${WEB_PORT}/api/health" >/dev/null; then
  end_step FAIL "GET web /api/health"
  exit 1
fi
end_step PASS "API /health /openapi.json /runs; web / /runs /api/health"

# --- 8. Scenario execution ---
begin_step "scenario"
if ! submit_out="$(make_in submit-run ARGS='--origin 2024-07-23 --n-paths 256 --wait 120' 2>&1)"; then
  printf '\n### submit-run A (failed)\n\n```\n%s\n```\n' "$(printf '%s\n' "$submit_out" | redact)" >> "$EXCERPTS"
  end_step FAIL "submit-run A"
  exit 1
fi
RUN_A="$(printf '%s\n' "$submit_out" | json_field run_id)"
STATUS_A="$(printf '%s\n' "$submit_out" | json_field status)"
if [ "$STATUS_A" != "succeeded" ]; then
  printf '\n### submit-run A\n\n```\n%s\n```\n' "$(printf '%s\n' "$submit_out" | redact)" >> "$EXCERPTS"
  end_step FAIL "run A status=$STATUS_A"
  exit 1
fi
run_a_json="$(curl -sf --max-time 10 "http://127.0.0.1:${API_PORT}/runs/${RUN_A}")"
SCENARIO="$(printf '%s\n' "$run_a_json" | json_field scenario_id)"
run_b_json="$(curl -sf --max-time 30 -X POST "http://127.0.0.1:${API_PORT}/runs" \
  -H "Content-Type: application/json" \
  -d "{\"scenario_id\":\"${SCENARIO}\",\"cutoff_ts\":\"2024-07-23T20:05:38Z\",\"seed\":7,\"n_paths\":256}")"
RUN_B="$(printf '%s\n' "$run_b_json" | json_field id)"
STATUS_B=""
i=0
while [ "$i" -lt 120 ]; do
  STATUS_B="$(curl -sf --max-time 10 "http://127.0.0.1:${API_PORT}/runs/${RUN_B}" | json_field status)"
  if [ "$STATUS_B" = "succeeded" ] || [ "$STATUS_B" = "failed" ]; then
    break
  fi
  i=$((i + 1))
  sleep 1
done
if [ "$STATUS_B" != "succeeded" ]; then
  end_step FAIL "run B status=$STATUS_B"
  exit 1
fi
results_a="$(curl -sf --max-time 10 "http://127.0.0.1:${API_PORT}/runs/${RUN_A}/results")"
n_results="$(printf '%s\n' "$results_a" | json_len)"
if [ "$n_results" -lt 1 ]; then
  end_step FAIL "run A results empty"
  exit 1
fi
if ! curl -sf --max-time 10 "http://127.0.0.1:${WEB_PORT}/api/runs/${RUN_A}/results" >/dev/null; then
  end_step FAIL "web proxy GET /api/runs/A/results"
  exit 1
fi
end_step PASS "run A $RUN_A worker; run B $RUN_B POST; $n_results result rows"

# --- 9. Replay (+ restart) ---
begin_step "replay"
if ! replay_a="$(make_in replay RUN="$RUN_A" 2>&1)"; then
  printf '\n### replay A (failed)\n\n```\n%s\n```\n' "$(printf '%s\n' "$replay_a" | redact)" >> "$EXCERPTS"
  end_step FAIL "replay A"
  exit 1
fi
if ! printf '%s\n' "$replay_a" | grep -q "status=exact_match"; then
  printf '\n### replay A\n\n```\n%s\n```\n' "$(printf '%s\n' "$replay_a" | redact)" >> "$EXCERPTS"
  end_step FAIL "run A not exact_match"
  exit 1
fi
if ! printf '%s\n' "$replay_a" | grep -q "llm_provider=''"; then
  end_step FAIL "run A replay llm_provider not empty"
  exit 1
fi
replay_b="$(curl -sf --max-time 60 -X POST "http://127.0.0.1:${API_PORT}/runs/${RUN_B}/replay")"
replay_b_status="$(printf '%s\n' "$replay_b" | json_field status)"
if [ "$replay_b_status" != "exact_match" ]; then
  printf '\n### replay B\n\n```\n%s\n```\n' "$(printf '%s\n' "$replay_b" | redact)" >> "$EXCERPTS"
  end_step FAIL "run B replay $replay_b_status"
  exit 1
fi
if ! make_in down >/dev/null; then
  end_step FAIL "make down before restart"
  exit 1
fi
if ! make_in up >/dev/null; then
  end_step FAIL "make up after restart"
  exit 1
fi
if ! replay_a2="$(make_in replay RUN="$RUN_A" 2>&1)"; then
  printf '\n### replay A after restart (failed)\n\n```\n%s\n```\n' "$(printf '%s\n' "$replay_a2" | redact)" >> "$EXCERPTS"
  end_step FAIL "replay A after restart"
  exit 1
fi
if ! printf '%s\n' "$replay_a2" | grep -q "status=exact_match"; then
  printf '\n### replay A after restart\n\n```\n%s\n```\n' "$(printf '%s\n' "$replay_a2" | redact)" >> "$EXCERPTS"
  end_step FAIL "run A after restart not exact_match"
  exit 1
fi
end_step PASS "A and B exact_match, llm unset; A exact_match after restart"

# --- 10. Tree cleanliness ---
begin_step "clean-tree"
dirty="$(git -C "$PKG" status --porcelain)"
if [ -n "$dirty" ]; then
  printf '\n### git status --porcelain\n\n```\n%s\n```\n' "$(printf '%s\n' "$dirty" | redact)" >> "$EXCERPTS"
  end_step FAIL "unpacked tree is dirty"
  exit 1
fi
end_step PASS "git status --porcelain empty"

echo "All verify steps passed." >&2
