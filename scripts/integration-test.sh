#!/usr/bin/env bash
# Isolated containers only; no implicit dotenv files or production volumes.
set -euo pipefail
cd "$(dirname "$0")/.."
project="fable-it-$$"
compose=(docker compose --env-file /dev/null -p "$project" -f tests/integration/compose.yml)
cleanup() { "${compose[@]}" down --volumes --remove-orphans; }
trap cleanup EXIT INT TERM
"${compose[@]}" up -d --wait --wait-timeout 90
pg_port=$("${compose[@]}" port postgres 5432)
redis_port=$("${compose[@]}" port redis 6379)
export FABLE_TEST_DATABASE_URL="postgresql://fable_test:fable_test@${pg_port}/fable_test"
export FABLE_TEST_REDIS_URL="redis://${redis_port}/0"
poetry run python -m unittest discover -s tests/integration -t . -v
