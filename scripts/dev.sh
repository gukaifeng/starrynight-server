#!/usr/bin/env bash
set -euo pipefail
BACKEND_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BACKEND_ROOT"
BACKEND_PG_BIN="${BACKEND_PG_BIN:-/opt/homebrew/opt/postgresql@17/bin}"
export PATH="$BACKEND_PG_BIN:$PATH"
mkdir -p .local/logs bin api
umask 077
if [ ! -f .local/environment ]; then
    BACKEND_DB_PASSWORD="$(openssl rand -hex 24)"
    BACKEND_REDIS_PASSWORD="$(openssl rand -hex 24)"
    cat > .local/environment <<EOF
export DATABASE_URL='postgres://starry:$BACKEND_DB_PASSWORD@127.0.0.1:55433/starry?sslmode=disable'
export TEST_DATABASE_URL='postgres://starry:$BACKEND_DB_PASSWORD@127.0.0.1:55433/starry_test?sslmode=disable'
export REDIS_URL='redis://:$BACKEND_REDIS_PASSWORD@127.0.0.1:56380/0'
export TEST_REDIS_URL='redis://:$BACKEND_REDIS_PASSWORD@127.0.0.1:56380/1'
export REDISCLI_AUTH='$BACKEND_REDIS_PASSWORD'
export PGPASSWORD='$BACKEND_DB_PASSWORD'
export STARRY_ENV=development
export STARRY_LISTEN=127.0.0.1:18090
export ALLOW_TEST_GUEST=true
EOF
    printf '%s' "$BACKEND_DB_PASSWORD" > .local/pg-password
    cat > .local/redis.conf <<EOF
bind 127.0.0.1
port 56380
requirepass $BACKEND_REDIS_PASSWORD
dir $BACKEND_ROOT/.local
appendonly yes
appendfsync everysec
maxmemory 256mb
maxmemory-policy noeviction
daemonize yes
pidfile $BACKEND_ROOT/.local/redis.pid
logfile $BACKEND_ROOT/.local/logs/redis.log
EOF
fi
source .local/environment
case "${1:-up}" in
    up)
        command -v go initdb pg_ctl redis-server >/dev/null
        if [ ! -f .local/postgres/PG_VERSION ]; then
            initdb -D .local/postgres --username=starry --auth-local=trust --auth-host=scram-sha-256 --pwfile=.local/pg-password > .local/logs/initdb.log
        fi
        if ! pg_ctl -D .local/postgres status >/dev/null 2>&1; then
            pg_ctl -D .local/postgres -l .local/logs/postgres.log -o "-h 127.0.0.1 -p 55433 -k $BACKEND_ROOT/.local" start
        fi
        for name in starry starry_test; do
            if [ "$(psql -h 127.0.0.1 -p 55433 -U starry -d postgres -Atc "SELECT count(*) FROM pg_database WHERE datname='$name'")" = 0 ]; then
                createdb -h 127.0.0.1 -p 55433 -U starry "$name"
            fi
        done
        if ! redis-cli -p 56380 ping >/dev/null 2>&1; then redis-server .local/redis.conf; fi
        go run ./cmd/migrate
        make build
        if [ -f .local/api.pid ] && kill -0 "$(cat .local/api.pid)" 2>/dev/null; then
            printf 'Existing API is running; restart with make dev-down then make dev-up to load code changes.\n'
        else
            nohup "$BACKEND_ROOT/bin/starry-api" > .local/logs/api.log 2>&1 < /dev/null &
            printf '%s' "$!" > .local/api.pid
        fi
        for attempt in {1..30}; do
            if curl -fsS http://127.0.0.1:18090/health/ready >/dev/null 2>&1; then
                printf 'StarryNight platform ready: http://127.0.0.1:18090/docs\n';exit 0
            fi
            sleep 1
        done
        printf 'API did not become ready; inspect .local/logs/api.log\n' >&2;exit 1
        ;;
    down)
        if [ -f .local/api.pid ]; then
            BACKEND_PID="$(cat .local/api.pid)"
            if ps -p "$BACKEND_PID" -o command= | rg -Fq "$BACKEND_ROOT/bin/starry-api"; then kill "$BACKEND_PID"; fi
            rm .local/api.pid
        fi
        redis-cli -p 56380 shutdown || true
        pg_ctl -D .local/postgres stop -m fast || true
        ;;
    *) printf 'Usage: scripts/dev.sh up|down\n' >&2;exit 2 ;;
esac
