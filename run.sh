#!/usr/bin/env bash
# Plain SQL builds the tables, Quack on Demand serves them.
#   ./run.sh        build, serve, query
#   ./run.sh stop   stop the recipe's gateway
set -euo pipefail
cd "$(dirname "$0")"

RECIPE_TOOL=sql
RECIPE_LABEL="plain SQL"
SERVE_TARGET=out/warehouse.duckdb

build_pipeline() {
  uv run --quiet python pipeline/run.py
}

# shellcheck source=lib/recipe.sh
source lib/recipe.sh
recipe_main "$@"
