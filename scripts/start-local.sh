#!/usr/bin/env bash
# Motivation vs Logic
# Motivation: One command should boot Quotient on a developer machine: MCP on
# 127.0.0.1:8080 and the Next.js portal, with the worker port the API already
# calls. apps/api/quotient/worker/port.py load_worker_port() file-loads
# apps/worker/quotient/port.py and calls load_port(). A process that started
# before that function existed keeps the memory ledger until this script is
# stopped and started again. A second worker service would be a different design.
# Bugs vs Fixes
# Bug: The header told the boot path that apps/worker had no load_port(), so a
# live pidfile was treated as a finished memory-ledger server.
# Fix: The header now matches the file loader. PYTHONPATH still puts apps/api
# ahead of apps/worker so `import quotient` stays the API package while
# load_port() can import loop and media. Recycle replaces the stale process.
# Logic: Load .env without printing it, require configured names (never
# JEV_TYPESAFE_API_KEY), force QUOTIENT_ENVIRONMENT=local, and set
# QUOTIENT_AUTH_BYPASS only after that check. Reuse /tmp/quotient-worker-venv
# or the repo .venv. pip install runs only when the API import check fails,
# and then only installs the apps/api runtime pins (starlette, uvicorn), not
# an editable checkout and not the worker tree. Bind uvicorn the way
# MCP.md does, bind next dev on 127.0.0.1:3000, wait until both ports answer
# HTTP, write pidfiles under .local/run, and stop only the children this
# process started. A live pidfile means print the existing URLs and exit.
# --logs sets QUOTIENT_AUDIT_LOG so the API process appends one JSON line per
# Bedrock call, Jev call, and MCP request to .local/run/audit.log, then this
# process follows that file. Credentials and request bodies are not written.
# A live MCP pid cannot pick up the flag; stop it and start again.
# This script does not call Bedrock, ffmpeg, or cdk.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${ROOT}/.local/run"
API_PIDFILE="${RUN_DIR}/api.pid"
WEB_PIDFILE="${RUN_DIR}/web.pid"
API_LOG="${RUN_DIR}/api.log"
WEB_LOG="${RUN_DIR}/web.log"
AUDIT_LOG="${RUN_DIR}/audit.log"
LOGS=0
TAIL_PID=""
MCP_HOST="127.0.0.1"
MCP_PORT="8080"
WEB_HOST="127.0.0.1"
WEB_PORT="3000"
MCP_URL="http://${MCP_HOST}:${MCP_PORT}/mcp"
PORTAL_URL="http://${WEB_HOST}:${WEB_PORT}"

# Names the local file must define. JEV_TYPESAFE_API_KEY is intentionally absent.
REQUIRED_NAMES=(
  AWS_BEDROCK_API_KEY
  AWS_BEDROCK_TRANSCRIBE
  AWS_BEDROCK_TRANSCRIBE_REGION
  AWS_BEDROCK_MEETING
  AWS_BEDROCK_LLM
  AWS_BEDROCK_SLM
)

STARTED_API=""
STARTED_WEB=""
CLEANED=0

die() {
  echo "$*" >&2
  exit 1
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --logs)
        LOGS=1
        shift
        ;;
      -h|--help)
        printf '%s\n' "usage: scripts/start-local.sh [--logs]" \
          "  --logs  record LLM and API calls in .local/run/audit.log and follow that file"
        exit 0
        ;;
      *)
        die "unknown argument: $1"
        ;;
    esac
  done
}

load_env() {
  local file="${ROOT}/.env"
  local line name value
  [[ -f "$file" ]] || die "missing .env; required variable names cannot be checked"
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    if [[ "$line" == export\ * ]]; then
      line="${line#export }"
      line="${line#"${line%%[![:space:]]*}"}"
    fi
    [[ "$line" == *=* ]] || die "malformed .env line (name missing '=')"
    name="${line%%=*}"
    value="${line#*=}"
    name="${name%"${name##*[![:space:]]}"}"
    [[ "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "malformed .env name: ${name}"
    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi
    printf -v "$name" '%s' "$value"
    export "$name"
  done <"$file"
}

require_names() {
  local name missing=()
  for name in "${REQUIRED_NAMES[@]}"; do
    if [[ -z "${!name:-}" ]]; then
      missing+=("$name")
    fi
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    die "missing required environment variable names: ${missing[*]}"
  fi
}

apply_local_env() {
  export QUOTIENT_ENVIRONMENT=local
  export QUOTIENT_MCP_URL="$MCP_URL"
  export QUOTIENT_RESOURCE_URL="$MCP_URL"
  # The API ignores QUOTIENT_AUTH_BYPASS when environment is staging or production.
  # Set the flag only after this script has forced the local environment.
  if [[ "$QUOTIENT_ENVIRONMENT" == "local" ]]; then
    export QUOTIENT_AUTH_BYPASS=1
  else
    unset QUOTIENT_AUTH_BYPASS || true
  fi
  export PYTHONPATH="${ROOT}/apps/api:${ROOT}/apps/worker${PYTHONPATH:+:$PYTHONPATH}"
}

python_imports() {
  local py="$1"
  "$py" -c 'import starlette, uvicorn, quotient.app' >/dev/null 2>&1
}

select_python() {
  local candidate
  local -a found=()
  for candidate in /tmp/quotient-worker-venv/bin/python "${ROOT}/.venv/bin/python"; do
    if [[ -x "$candidate" ]]; then
      found+=("$candidate")
      if python_imports "$candidate"; then
        PYTHON="$candidate"
        return 0
      fi
    fi
  done
  [[ ${#found[@]} -gt 0 ]] || die "no virtualenv at /tmp/quotient-worker-venv or ${ROOT}/.venv"
  PYTHON="${found[0]}"
  echo "import check failed; installing starlette and uvicorn into ${PYTHON}" >&2
  "$PYTHON" -m pip install --disable-pip-version-check 'starlette>=0.41' 'uvicorn>=0.32' >/dev/null
  python_imports "$PYTHON" || die "API import check still failing after installing starlette and uvicorn"
}

pid_alive() {
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ ]] && [[ "$pid" -gt 1 ]] && kill -0 "$pid" 2>/dev/null
}

pid_running() {
  local pid="$1" stat
  pid_alive "$pid" || return 1
  stat="$(ps -o stat= -p "$pid" 2>/dev/null | tr -d '[:space:]' || true)"
  [[ "$stat" == Z* ]] && return 1
  return 0
}

process_args() {
  ps -p "$1" -ww -o args= 2>/dev/null || true
}

api_process() {
  local args
  args="$(process_args "$1")"
  [[ "$args" == *"quotient.app:create_app"* && "$args" == *"${MCP_PORT}"* ]]
}

web_process() {
  local args
  args="$(process_args "$1")"
  [[ "$args" == *"next"* && "$args" == *"dev"* && "$args" == *"${WEB_PORT}"* ]]
}

read_pidfile() {
  local file="$1"
  local pid=""
  if [[ -f "$file" ]]; then
    IFS= read -r pid <"$file" || true
  fi
  printf '%s' "$pid"
}

listening_pid() {
  local port="$1"
  local holder
  holder="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
  holder="${holder%%$'\n'*}"
  printf '%s' "$holder"
}

is_under() {
  local parent="$1" current="$2" hops=0
  while [[ -n "$current" && "$current" != "0" && "$current" != "1" && "$hops" -lt 20 ]]; do
    [[ "$current" == "$parent" ]] && return 0
    current="$(ps -o ppid= -p "$current" 2>/dev/null | tr -d '[:space:]' || true)"
    hops=$((hops + 1))
  done
  return 1
}

assert_port_available() {
  local port="$1" owner="$2"
  local holder
  holder="$(listening_pid "$port")"
  [[ -z "$holder" ]] && return 0
  if [[ -n "$owner" ]] && { [[ "$holder" == "$owner" ]] || is_under "$owner" "$holder"; }; then
    return 0
  fi
  die "port ${port} is already in use by pid ${holder}; refusing to stop that process"
}

kill_tree() {
  local pid="$1" signal="$2" child
  [[ -n "$pid" ]] || return 0
  while IFS= read -r child; do
    [[ -n "$child" ]] || continue
    kill_tree "$child" "$signal"
  done < <(pgrep -P "$pid" 2>/dev/null || true)
  kill "-${signal}" "$pid" 2>/dev/null || true
}

stop_one() {
  local pid="$1"
  local i
  if ! pid_running "$pid"; then
    wait "$pid" 2>/dev/null || true
    return 0
  fi
  kill_tree "$pid" TERM
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if ! pid_running "$pid"; then
      wait "$pid" 2>/dev/null || true
      return 0
    fi
    sleep 0.3
  done
  kill_tree "$pid" KILL
  wait "$pid" 2>/dev/null || true
}

clear_pidfile_if_ours() {
  local file="$1" pid="$2" current
  [[ -n "$pid" && -f "$file" ]] || return 0
  current="$(read_pidfile "$file")"
  if [[ "$current" == "$pid" ]]; then
    rm -f "$file"
  fi
}

cleanup() {
  [[ "$CLEANED" -eq 0 ]] || return 0
  CLEANED=1
  if [[ -n "$TAIL_PID" ]]; then
    kill "$TAIL_PID" 2>/dev/null || true
    wait "$TAIL_PID" 2>/dev/null || true
    TAIL_PID=""
  fi
  stop_one "$STARTED_API"
  stop_one "$STARTED_WEB"
  clear_pidfile_if_ours "$API_PIDFILE" "$STARTED_API"
  clear_pidfile_if_ours "$WEB_PIDFILE" "$STARTED_WEB"
}

on_signal() {
  cleanup
  exit 0
}

trap on_signal INT TERM HUP
trap cleanup EXIT

wait_http() {
  local url="$1" pid="$2"
  local attempt
  for attempt in $(seq 1 180); do
    if curl --silent --output /dev/null --max-time 2 "$url"; then
      return 0
    fi
    if ! pid_alive "$pid"; then
      die "process ${pid} exited before ${url} answered"
    fi
    sleep 1
  done
  die "timed out waiting for HTTP from ${url}"
}

launch_api() {
  # Bugs vs Fixes
  # Bug: set -m put uvicorn in a background process group with the terminal
  # still on stdin. The PCM ffmpeg then took SIGTTIN and the whole API stopped.
  # Fix: Drop monitor mode and attach stdin to /dev/null. Logs stay on the file.
  : >"$API_LOG"
  "$PYTHON" -m uvicorn quotient.app:create_app --factory --app-dir "${ROOT}/apps/api" \
    --host "$MCP_HOST" --port "$MCP_PORT" >>"$API_LOG" 2>&1 </dev/null &
  STARTED_API=$!
  disown "$STARTED_API" 2>/dev/null || true
  printf '%s\n' "$STARTED_API" >"$API_PIDFILE"
}

launch_web() {
  local next_bin="${ROOT}/apps/web/node_modules/.bin/next"
  [[ -x "$next_bin" ]] || die "missing ${next_bin}"
  : >"$WEB_LOG"
  (
    cd "${ROOT}/apps/web"
    exec "$next_bin" dev --hostname "$WEB_HOST" --port "$WEB_PORT"
  ) >>"$WEB_LOG" 2>&1 </dev/null &
  STARTED_WEB=$!
  disown "$STARTED_WEB" 2>/dev/null || true
  printf '%s\n' "$STARTED_WEB" >"$WEB_PIDFILE"
}

follow_audit() {
  [[ "$LOGS" -eq 1 ]] || return 0
  touch "$AUDIT_LOG"
  tail -n 0 -F "$AUDIT_LOG" &
  TAIL_PID=$!
}

main() {
  local api_pid="" web_pid=""
  parse_args "$@"
  cd "$ROOT"
  mkdir -p "$RUN_DIR"
  load_env
  require_names
  apply_local_env
  if [[ "$LOGS" -eq 1 ]]; then
    export QUOTIENT_AUDIT_LOG="$AUDIT_LOG"
    touch "$AUDIT_LOG"
  fi
  select_python

  api_pid="$(read_pidfile "$API_PIDFILE")"
  if pid_alive "$api_pid" && api_process "$api_pid"; then
    :
  else
    api_pid=""
    rm -f "$API_PIDFILE"
  fi
  web_pid="$(read_pidfile "$WEB_PIDFILE")"
  if pid_alive "$web_pid" && web_process "$web_pid"; then
    :
  else
    web_pid=""
    rm -f "$WEB_PIDFILE"
  fi

  if [[ "$LOGS" -eq 1 && -n "$api_pid" ]]; then
    die "mcp pid ${api_pid} is already running; stop it, then start with --logs"
  fi

  if [[ -n "$api_pid" && -n "$web_pid" ]]; then
    printf 'mcp %s pid %s\n' "$MCP_URL" "$api_pid"
    printf 'portal %s pid %s\n' "$PORTAL_URL" "$web_pid"
    CLEANED=1
    exit 0
  fi

  if [[ -z "$api_pid" ]]; then
    assert_port_available "$MCP_PORT" ""
  fi
  if [[ -z "$web_pid" ]]; then
    assert_port_available "$WEB_PORT" ""
  fi

  if [[ -z "$api_pid" ]]; then
    launch_api
    api_pid="$STARTED_API"
  fi
  if [[ -z "$web_pid" ]]; then
    launch_web
    web_pid="$STARTED_WEB"
  fi

  wait_http "http://${MCP_HOST}:${MCP_PORT}/mcp" "$api_pid"
  wait_http "$PORTAL_URL" "$web_pid"

  printf 'mcp %s pid %s\n' "$MCP_URL" "$api_pid"
  printf 'portal %s pid %s\n' "$PORTAL_URL" "$web_pid"
  if [[ "$LOGS" -eq 1 ]]; then
    printf 'audit %s\n' "$AUDIT_LOG"
  fi
  follow_audit

  while pid_running "$api_pid" && pid_running "$web_pid"; do
    sleep 1
  done
  wait "$api_pid" 2>/dev/null || true
  wait "$web_pid" 2>/dev/null || true
}

main "$@"
