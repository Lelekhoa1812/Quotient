#!/usr/bin/env bash
# Motivation vs Logic
# Motivation: Stop the MCP API and portal started by scripts/start-local.sh
# without touching user media or any process that does not match those pidfiles.
# Logic: Read .local/run pidfiles, signal TERM then KILL only when the process
# arguments are uvicorn quotient.app:create_app or next dev on the local ports,
# and delete those pidfiles. A pid that belongs to something else is reported
# and left running.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${ROOT}/.local/run"
API_PIDFILE="${RUN_DIR}/api.pid"
WEB_PIDFILE="${RUN_DIR}/web.pid"
MCP_PORT="8080"
WEB_PORT="3000"

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

read_pidfile() {
  local file="$1"
  local pid=""
  if [[ -f "$file" ]]; then
    IFS= read -r pid <"$file" || true
  fi
  printf '%s' "$pid"
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

stop_pid() {
  local pid="$1"
  local i
  pid_running "$pid" || return 0
  kill_tree "$pid" TERM
  for i in 1 2 3 4 5 6 7 8 9 10; do
    pid_running "$pid" || return 0
    sleep 0.3
  done
  kill_tree "$pid" KILL
}

stop_recorded() {
  local role="$1" file="$2" pid args match=0
  pid="$(read_pidfile "$file")"
  if [[ -z "$pid" ]]; then
    return 0
  fi
  if ! pid_running "$pid"; then
    rm -f "$file"
    echo "stopped ${role} pid ${pid} (already exited)"
    return 0
  fi
  args="$(process_args "$pid")"
  if [[ "$role" == "mcp" ]]; then
    [[ "$args" == *"quotient.app:create_app"* && "$args" == *"${MCP_PORT}"* ]] && match=1
  else
    [[ "$args" == *"next"* && "$args" == *"dev"* && "$args" == *"${WEB_PORT}"* ]] && match=1
  fi
  if [[ "$match" -ne 1 ]]; then
    echo "pid ${pid} in ${file} is not a local Quotient ${role} process; left running" >&2
    return 0
  fi
  stop_pid "$pid"
  rm -f "$file"
  echo "stopped ${role} pid ${pid}"
}

stop_recorded mcp "$API_PIDFILE"
stop_recorded portal "$WEB_PIDFILE"
