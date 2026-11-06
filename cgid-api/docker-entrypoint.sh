#!/bin/sh
set -e

# Run another command instead of the server, e.g.:
#   docker compose run --rm api python -m app.doctor
if [ "$#" -gt 0 ]; then
  exec "$@"
fi

# Demo mode: with no DATABASE_URL the app uses its own throwaway SQLite file,
# so load the demo data on start and everything works out of the box.
#
# With your own database, nothing is seeded unless you opt in with
# SEED_DEMO_DATA=true (the seed script also refuses to wipe a non-SQLite
# database unless SEED_ALLOW_RESET=true).
if [ -z "${DATABASE_URL}" ] && [ -z "${SEED_DEMO_DATA}" ]; then
  SEED_DEMO_DATA=true
fi

if [ "${SEED_DEMO_DATA}" = "true" ]; then
  python -m app.seed
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
