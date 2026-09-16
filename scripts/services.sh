#!/usr/bin/env bash
#
# Interactive start/stop/status for the Temporal LangGraph OTel reference app.
#
# Manages two kinds of things:
#   - infrastructure  (Temporal, OTel Collector, Prometheus, Grafana) via Docker
#   - the worker      (a local background Python process)
#
# Reachability is checked by probing ports/HTTP, so a dependency is detected
# whether it runs as a Docker container or as a native service. Docker presence
# is reported additionally when found.
#
# Usage:
#   scripts/services.sh                 # interactive menu
#   scripts/services.sh status
#   scripts/services.sh start           # infra (if needed) + worker
#   scripts/services.sh stop            # worker (infra is left running)
#   scripts/services.sh start-infra | stop-infra
#   scripts/services.sh start-worker | stop-worker
#   scripts/services.sh run "What time is it?"
#   scripts/services.sh logs
#
# Config: override via environment or a local .env in the repo root.

set -uo pipefail

# --- paths -------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_DIR="$REPO_ROOT/.run"
WORKER_PID_FILE="$RUN_DIR/worker.pid"
WORKER_LOG="$RUN_DIR/worker.log"
COMPOSE_FILE="$REPO_ROOT/docker-compose.yml"
mkdir -p "$RUN_DIR"

# Load .env if present (for endpoint/port overrides).
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a; # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"; set +a
fi

# --- config (defaults match the reference docker-compose) --------------------
TEMPORAL_ADDRESS="${TEMPORAL_ADDRESS:-localhost:7233}"
OTEL_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4317}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"
GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"

# --- python interpreter ------------------------------------------------------
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PY="$REPO_ROOT/.venv/bin/python"
else
  PY="$(command -v python3 || command -v python || true)"
fi

# --- colours (only on a TTY) -------------------------------------------------
if [[ -t 1 ]]; then
  C_OK=$'\033[32m'; C_BAD=$'\033[31m'; C_DIM=$'\033[2m'; C_HDR=$'\033[1;36m'; C_RST=$'\033[0m'
else
  C_OK=""; C_BAD=""; C_DIM=""; C_HDR=""; C_RST=""
fi

log()  { printf '%s\n' "$*"; }
ok()   { printf '%s[ UP ]%s %s\n'   "$C_OK"  "$C_RST" "$*"; }
bad()  { printf '%s[DOWN]%s %s\n'   "$C_BAD" "$C_RST" "$*"; }
hdr()  { printf '\n%s%s%s\n' "$C_HDR" "$*" "$C_RST"; }

# --- probes ------------------------------------------------------------------
split_host()  { local t="${1#*://}"; echo "${t%%:*}"; }
split_port()  { local t="${1#*://}"; case "$t" in *:*) echo "${t##*:}";; *) echo "";; esac; }

tcp_open() { # host port
  local host="$1" port="$2"
  if command -v nc >/dev/null 2>&1; then
    nc -z -w2 "$host" "$port" >/dev/null 2>&1
  else
    (exec 3<>"/dev/tcp/$host/$port") >/dev/null 2>&1
  fi
}

http_ok() { # url
  curl -fsS -m 3 -o /dev/null "$1" >/dev/null 2>&1
}

docker_match() { # name-substring -> prints the shortest matching running container
  command -v docker >/dev/null 2>&1 || return 1
  # Shortest name wins so "temporal" resolves to the "temporal" container rather
  # than a longer compound like "...-otel-collector-1".
  docker ps --format '{{.Names}}' 2>/dev/null | grep -i -- "$1" \
    | awk '{ print length, $0 }' | sort -n | head -1 | cut -d' ' -f2-
}

worker_pid() {
  if [[ -f "$WORKER_PID_FILE" ]]; then
    local pid; pid="$(cat "$WORKER_PID_FILE" 2>/dev/null)"
    if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then echo "$pid"; return 0; fi
  fi
  # Fall back to a process scan (worker started outside this script).
  pgrep -f "app.entrypoints.worker" 2>/dev/null | head -1
}

note_docker() { # substring
  local c; c="$(docker_match "$1" || true)"
  [[ -n "$c" ]] && printf '%s(docker: %s)%s' "$C_DIM" "$c" "$C_RST"
}

# --- status ------------------------------------------------------------------
status() {
  hdr "Infrastructure"

  local h p
  h="$(split_host "$TEMPORAL_ADDRESS")"; p="$(split_port "$TEMPORAL_ADDRESS")"
  if tcp_open "$h" "${p:-7233}"; then ok "Temporal        $TEMPORAL_ADDRESS $(note_docker temporal)"
  else bad "Temporal        $TEMPORAL_ADDRESS"; fi

  h="$(split_host "$OTEL_ENDPOINT")"; p="$(split_port "$OTEL_ENDPOINT")"
  if tcp_open "$h" "${p:-4317}"; then ok "OTel Collector  $OTEL_ENDPOINT $(note_docker otel-collector)"
  else bad "OTel Collector  $OTEL_ENDPOINT"; fi

  if http_ok "${PROMETHEUS_URL%/}/-/healthy"; then ok "Prometheus      $PROMETHEUS_URL $(note_docker prometheus)"
  else bad "Prometheus      $PROMETHEUS_URL"; fi

  if http_ok "${GRAFANA_URL%/}/api/health"; then ok "Grafana         $GRAFANA_URL $(note_docker grafana)"
  else bad "Grafana         $GRAFANA_URL"; fi

  hdr "Worker"
  local wpid; wpid="$(worker_pid || true)"
  if [[ -n "$wpid" ]]; then ok "Worker          pid $wpid  (log: $WORKER_LOG)"
  else bad "Worker          not running"; fi
  echo
}

# --- docker helpers ----------------------------------------------------------
require_docker() {
  command -v docker >/dev/null 2>&1 || { log "${C_BAD}docker is not installed / on PATH${C_RST}"; return 1; }
  docker info >/dev/null 2>&1 || { log "${C_BAD}docker daemon is not reachable${C_RST}"; return 1; }
}

start_infra() {
  require_docker || return 1
  log "Starting infrastructure via docker compose ..."
  docker compose -f "$COMPOSE_FILE" up -d || return 1
  log "Waiting for services to become healthy ..."
  local deadline=$((SECONDS + 120))
  while (( SECONDS < deadline )); do
    if tcp_open "$(split_host "$TEMPORAL_ADDRESS")" "$(split_port "$TEMPORAL_ADDRESS")" \
       && http_ok "${PROMETHEUS_URL%/}/-/healthy" \
       && http_ok "${GRAFANA_URL%/}/api/health"; then
      log "${C_OK}Infrastructure is up.${C_RST}"; return 0
    fi
    sleep 3
  done
  log "${C_BAD}Timed out waiting for infrastructure; check 'docker compose logs'.${C_RST}"
  return 1
}

stop_infra() {
  require_docker || return 1
  log "Stopping infrastructure (docker compose down) ..."
  docker compose -f "$COMPOSE_FILE" down
}

# --- worker helpers ----------------------------------------------------------
start_worker() {
  local wpid; wpid="$(worker_pid || true)"
  if [[ -n "$wpid" ]]; then log "${C_DIM}Worker already running (pid $wpid).${C_RST}"; return 0; fi
  [[ -n "$PY" ]] || { log "${C_BAD}No python interpreter found (create .venv: make install).${C_RST}"; return 1; }

  log "Starting worker ..."
  ( cd "$REPO_ROOT" && PYTHONPATH="$REPO_ROOT" PYTHONUNBUFFERED=1 \
      setsid nohup "$PY" -m app.entrypoints.worker >"$WORKER_LOG" 2>&1 </dev/null & )
  # Capture the actual python child pid (setsid detaches).
  sleep 3
  local pid; pid="$(pgrep -f 'app.entrypoints.worker' | head -1)"
  if [[ -n "$pid" ]]; then
    echo "$pid" > "$WORKER_PID_FILE"
    if grep -q worker.running "$WORKER_LOG" 2>/dev/null; then
      log "${C_OK}Worker running (pid $pid).${C_RST}"
    else
      log "${C_DIM}Worker starting (pid $pid); tail $WORKER_LOG for progress.${C_RST}"
    fi
  else
    log "${C_BAD}Worker failed to start; last log lines:${C_RST}"; tail -n 15 "$WORKER_LOG" 2>/dev/null
    return 1
  fi
}

stop_worker() {
  local wpid; wpid="$(worker_pid || true)"
  if [[ -z "$wpid" ]]; then log "${C_DIM}Worker is not running.${C_RST}"; rm -f "$WORKER_PID_FILE"; return 0; fi
  log "Stopping worker (pid $wpid) ..."
  kill "$wpid" >/dev/null 2>&1
  for _ in 1 2 3 4 5; do kill -0 "$wpid" >/dev/null 2>&1 || break; sleep 1; done
  if kill -0 "$wpid" >/dev/null 2>&1; then kill -9 "$wpid" >/dev/null 2>&1; fi
  rm -f "$WORKER_PID_FILE"
  log "${C_OK}Worker stopped.${C_RST}"
}

run_workflow() {
  local msg="${1:-}"
  if [[ -z "$msg" ]]; then read -r -p "Message: " msg; fi
  [[ -n "$PY" ]] || { log "${C_BAD}No python interpreter found.${C_RST}"; return 1; }
  ( cd "$REPO_ROOT" && PYTHONPATH="$REPO_ROOT" "$PY" -m app.entrypoints.workflow --message "$msg" )
}

tail_logs() {
  [[ -f "$WORKER_LOG" ]] || { log "${C_DIM}No worker log yet.${C_RST}"; return 0; }
  log "${C_DIM}Tailing $WORKER_LOG (Ctrl-C to stop)...${C_RST}"
  tail -n 40 -f "$WORKER_LOG"
}

# --- interactive menu --------------------------------------------------------
menu() {
  while true; do
    status
    cat <<EOF
  1) Start infrastructure        5) Stop worker
  2) Stop infrastructure         6) Run a workflow
  3) Start worker                7) Tail worker logs
  4) Start everything            8) Refresh status
  q) Quit
EOF
    read -r -p "> " choice
    case "$choice" in
      1) start_infra ;;
      2) stop_infra ;;
      3) start_worker ;;
      4) start_infra && start_worker ;;
      5) stop_worker ;;
      6) run_workflow ;;
      7) tail_logs ;;
      8) : ;;
      q|Q) log "bye"; exit 0 ;;
      *) log "unknown option: $choice" ;;
    esac
    [[ "$choice" == "7" ]] || { read -r -p "press enter to continue " _; }
  done
}

# --- entrypoint --------------------------------------------------------------
case "${1:-menu}" in
  menu)          menu ;;
  status)        status ;;
  start)         start_infra && start_worker ;;
  stop)          stop_worker ;;
  start-infra)   start_infra ;;
  stop-infra)    stop_infra ;;
  start-worker)  start_worker ;;
  stop-worker)   stop_worker ;;
  run)           shift; run_workflow "${*:-}" ;;
  logs)          tail_logs ;;
  *) log "usage: $0 {menu|status|start|stop|start-infra|stop-infra|start-worker|stop-worker|run <msg>|logs}"; exit 2 ;;
esac
