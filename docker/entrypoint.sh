#!/bin/sh
set -e
if [ -n "$DATABASE_URL" ]; then
  SYNC_URL="$DATABASE_URL"
  case "$SYNC_URL" in
    postgresql+asyncpg://*)
      SYNC_URL=$(printf '%s' "$SYNC_URL" | sed 's|^postgresql+asyncpg://|postgresql+psycopg://|')
      ;;
  esac
  DATABASE_URL="$SYNC_URL" alembic upgrade head
fi
exec "$@"
