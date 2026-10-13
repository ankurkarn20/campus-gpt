#!/usr/bin/env bash
# Manage the local development PostgreSQL cluster.
#
#   scripts/db.sh start | stop | status | psql [args...]
#
# Uses a system PostgreSQL 16 if installed, otherwise the user-local copy in
# ~/.local/pgsql (installed without root). Override with PG_BIN=/path/to/bin.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="${CAMPUSGPT_STATE:-$HOME/.local/share/campus-gpt}"
DATA="$STATE/pgdata"
LOG="$STATE/postgres.log"

if [[ -z "${PG_BIN:-}" ]]; then
  if [[ -x /usr/lib/postgresql/16/bin/pg_ctl ]]; then
    PG_BIN=/usr/lib/postgresql/16/bin
  else
    PG_BIN="$HOME/.local/pgsql/usr/lib/postgresql/16/bin"
    export LD_LIBRARY_PATH="$HOME/.local/pgsql/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  fi
fi

case "${1:-status}" in
  start)  "$PG_BIN/pg_ctl" -D "$DATA" -l "$LOG" -w start ;;
  stop)   "$PG_BIN/pg_ctl" -D "$DATA" -w stop ;;
  status) "$PG_BIN/pg_ctl" -D "$DATA" status ;;
  psql)
    shift
    # Connect as the application role using DATABASE_URL from .env
    url="$(grep -E '^DATABASE_URL=' "$ROOT/.env" | cut -d= -f2- | sed 's/+psycopg//')"
    exec "$PG_BIN/psql" "$url" "$@" ;;
  *) echo "usage: $0 start|stop|status|psql" >&2; exit 2 ;;
esac
