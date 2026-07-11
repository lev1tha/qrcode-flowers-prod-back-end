#!/bin/sh
set -e

echo "→ Applying database migrations…"
python manage.py migrate --noinput

echo "→ Collecting static files…"
python manage.py collectstatic --noinput

# Стартовые данные — только по явному флагу (первичный bootstrap).
if [ "${RUN_SEED:-0}" = "1" ]; then
  echo "→ Seeding initial data…"
  python manage.py seed
fi

echo "→ Starting: $*"
exec "$@"
