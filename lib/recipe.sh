# shellcheck shell=bash
# Shared lifecycle for the Quack on Demand recipes. Identical in every
# qod-recipe-* repo: change it in qod-recipe-sql and copy it over.
#
# The caller (run.sh) sets RECIPE_TOOL, RECIPE_LABEL and SERVE_TARGET, defines
# build_pipeline, sources this file and calls `recipe_main "$@"`.
#
# Everything the recipe's gateway keeps lives under out/: QOD_DATA_DIR and
# QOD_CONFIG_FILE point there, so the reader's own QoD install, password and
# CLI profile are never read or written. The gateway listens on 127.0.0.1 only.

QOD_CMD="${QOD_CMD:-uvx qod@latest}"
QOD_MIN_VERSION="0.15.1"
RECIPE_PASSWORD="recipe-admin"
# Manager REST, manager internal, FlightSQL edge, native Quack, embedded Postgres.
RECIPE_PORTS="20900 20901 31338 9494 25432"
READY_TIMEOUT_S="${READY_TIMEOUT_S:-300}"

say() { printf '%s\n' "$*"; }
die() {
  local code=$1
  shift
  printf 'error: %s\n' "$*" >&2
  exit "$code"
}

# version_ge A B: true when A >= B, comparing the first three numeric parts
# (0.15.1.dev0 counts as 0.15.1).
version_ge() {
  local a b i x y
  IFS=. read -r -a a <<<"$1"
  IFS=. read -r -a b <<<"$2"
  for i in 0 1 2; do
    x=${a[$i]:-0}
    y=${b[$i]:-0}
    x=${x%%[!0-9]*}
    y=${y%%[!0-9]*}
    x=${x:-0}
    y=${y:-0}
    if ((10#$x > 10#$y)); then return 0; fi
    if ((10#$x < 10#$y)); then return 1; fi
  done
  return 0
}

port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

qod() {
  local argv
  read -r -a argv <<<"$QOD_CMD"
  "${argv[@]}" "$@"
}

recipe_preflight() {
  command -v uv >/dev/null 2>&1 || die 2 "uv is required: https://docs.astral.sh/uv/getting-started/installation/"
  local p
  for p in $RECIPE_PORTS; do
    if port_busy "$p"; then
      die 2 "port $p is already in use. If another qod-recipe is running, run ./run.sh stop in its folder; if it is your own QoD gateway, stop it with Ctrl-C in its terminal. Then run ./run.sh again."
    fi
  done
  local line version
  line=$(qod --version 2>/dev/null | tail -n 1) || die 2 "could not run '$QOD_CMD --version'"
  version=${line##* }
  if ! version_ge "$version" "$QOD_MIN_VERSION"; then
    die 2 "this recipe needs qod $QOD_MIN_VERSION or later, found '$version'. uvx may be holding an old copy: run 'uvx qod@latest --version' to refresh it."
  fi
  # A recipe's own prerequisites (Spark's JDK, say): define recipe_extra_preflight in run.sh.
  if declare -F recipe_extra_preflight >/dev/null; then
    recipe_extra_preflight
  fi
}

recipe_stop() {
  local pidfile=out/qod.pid pid args i
  [ -f "$pidfile" ] || return 0
  pid=$(tr -dc '0-9' <"$pidfile")
  args=$(ps -o args= -p "${pid:-0}" 2>/dev/null || true)
  # Only this recipe's gateway carries --name recipe_<tool> (trailing space:
  # recipe_sql must not match recipe_sqlmesh).
  case "$args " in
    *serve*"--name recipe_$RECIPE_TOOL "*) ;;
    *)
      rm -f "$pidfile"
      say "removed a stale out/qod.pid (process ${pid:-?} is not this recipe's gateway)"
      return 0
      ;;
  esac
  say "stopping the recipe gateway (pid $pid)..."
  # The gateway runs in its own process group: signal the group, as Ctrl-C would.
  kill -INT -- "-$pid" 2>/dev/null || true
  for i in $(seq 1 90); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM -- "-$pid" 2>/dev/null || true
    sleep 5
  fi
  for i in $(seq 1 30); do
    port_busy 20900 || port_busy 31338 || break
    sleep 1
  done
  rm -f "$pidfile"
  say "stopped"
}

# Exec the gateway with none of the reader's QOD_* or PROXY_* settings (data
# paths, ports, admin name, session, profile...), then only the recipe's own.
recipe_exec_gateway() {
  local v
  for v in $(env | awk -F= '/^(QOD|PROXY)_[A-Za-z0-9_]*=/ {print $1}'); do
    unset "$v"
  done
  export QOD_DATA_DIR="$PWD/out/.qod"
  export QOD_CONFIG_FILE="$PWD/out/.qod/config.toml"
  export QOD_ADMIN_PASSWORD="$RECIPE_PASSWORD"
  export PROXY_HOST=127.0.0.1 QOD_QUACK_HOST=127.0.0.1 QOD_ON_DEMAND_HOST=127.0.0.1 QOD_NODE_BIND=127.0.0.1
  exec "$@"
}

recipe_serve() {
  mkdir -p out/.qod

  say "starting Quack on Demand on $SERVE_TARGET (state in out/.qod, log in out/qod.log)..."
  local pid argv waited=0
  read -r -a argv <<<"$QOD_CMD"
  # Background the command itself, not the qod() function: a function would
  # run in a subshell and $! would be that subshell, not the gateway.
  # set -m gives the gateway its own process group, so recipe_stop can signal
  # all of it at once, as Ctrl-C would.
  set -m
  (recipe_exec_gateway "${argv[@]}" serve "$SERVE_TARGET" --name "recipe_$RECIPE_TOOL") >out/qod.log 2>&1 </dev/null &
  pid=$!
  set +m
  echo "$pid" >out/qod.pid
  # Ctrl-C while waiting: the gateway has its own process group, so stop it here.
  trap 'recipe_stop; exit 130' INT TERM

  until uv run --quiet query.py --probe; do
    if ! kill -0 "$pid" 2>/dev/null; then
      tail -n 30 out/qod.log >&2
      rm -f out/qod.pid
      die 1 "the gateway exited during startup (full log: out/qod.log)"
    fi
    if [ "$waited" -ge "$READY_TIMEOUT_S" ]; then
      tail -n 30 out/qod.log >&2
      recipe_stop
      die 1 "the gateway was not ready after ${READY_TIMEOUT_S}s (full log: out/qod.log)"
    fi
    sleep 2
    waited=$((waited + 2))
  done
  trap - INT TERM
  say "QoD serving default_recipe_$RECIPE_TOOL on localhost:31338 (tenant=default, pool=bi)"
}

recipe_connect_hint() {
  local p="$RECIPE_PASSWORD"
  cat <<EOF

Connect your own tool (user admin, password $p):
  JDBC   jdbc:arrow-flight-sql://localhost:31338/?tenant=default&pool=bi&user=admin&superuser=true&useEncryption=true&disableCertificateVerification=true
  ADBC   uri=grpc+tls://localhost:31338 (adbc_driver_flightsql; username, password, grpc headers tenant=default, pool=bi, superuser=true)
  ODBC   Driver={Arrow Flight SQL ODBC Driver};Host=localhost;Port=31338;UseEncryption=true;DisableCertificateVerification=true;UID=admin;PWD=$p;SUPERUSER=true;TENANT=default;POOL=bi
  DuckDB ATTACH 'quack:localhost:9494' AS qod (TYPE quack, TOKEN 'tenant=default&pool=bi&user=admin&password=$p&superuser=true');
  Admin UI http://localhost:20900/ui/

Stop: ./run.sh stop    Clean up: rm -rf out
EOF
}

recipe_main() {
  if [ "${1:-}" = "stop" ]; then
    recipe_stop
    return 0
  fi
  [ $# -eq 0 ] || die 2 "usage: ./run.sh [stop]"

  recipe_stop
  recipe_preflight
  rm -rf out
  mkdir out
  uv sync --quiet
  build_pipeline
  say "$RECIPE_LABEL built customers_enriched and daily_revenue into $SERVE_TARGET"
  # query.py reads these: pin them so the reader's own QOD_* variables cannot leak in.
  export QOD_HOST=127.0.0.1 QOD_PORT=31338 QOD_USER=admin QOD_PASSWORD="$RECIPE_PASSWORD"
  export QOD_TENANT=default QOD_POOL=bi QOD_SUPERUSER=true QOD_TLS=true QOD_TLS_VERIFY=false
  recipe_serve
  if ! uv run --quiet query.py --check; then
    say "the gateway is still running: ./run.sh stop stops it, out/qod.log has its log" >&2
    exit 1
  fi
  recipe_connect_hint
}
