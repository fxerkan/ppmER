#!/bin/sh
# Metabase auto-setup: completes setup wizard + data warehouse connection
# Uses setup token API for first run, falls back to session login for re-runs

set -e

MB_URL="http://metabase:3000"
ADMIN_EMAIL="${MB_ADMIN_EMAIL:-admin@ppm.local}"
ADMIN_PASSWORD="${MB_ADMIN_PASSWORD:-PpmAdmin123!}"
ADMIN_NAME="${MB_ADMIN_NAME:-PPM Admin}"
DB_USER="${POSTGRES_USER:-ppm_user}"
DB_PASS="${POSTGRES_PASSWORD:-ppm_password}"

echo "Waiting for Metabase to be ready..."
for i in $(seq 1 120); do
  if curl -s "${MB_URL}/api/health" 2>/dev/null | grep -q '"status":"ok"'; then
    echo "Metabase is ready!"
    break
  fi
  if [ "$i" -eq 120 ]; then
    echo "ERROR: Metabase did not become ready in time."
    exit 1
  fi
  sleep 5
done

# Check if setup is needed via setup-token
SETUP_TOKEN=$(curl -s "${MB_URL}/api/session/properties" | python3 -c "import json,sys; print(json.load(sys.stdin).get('setup-token',''))" 2>/dev/null || echo "")

if [ -n "$SETUP_TOKEN" ]; then
  echo "First-time setup detected. Completing setup with admin + database..."

  FIRST_NAME="${ADMIN_NAME%% *}"
  LAST_NAME="${ADMIN_NAME#* }"
  [ "$FIRST_NAME" = "$LAST_NAME" ] && LAST_NAME="Admin"

  PAYLOAD=$(cat <<ENDJSON
{
  "token": "${SETUP_TOKEN}",
  "user": {
    "first_name": "${FIRST_NAME}",
    "last_name": "${LAST_NAME}",
    "email": "${ADMIN_EMAIL}",
    "password": "${ADMIN_PASSWORD}"
  },
  "prefs": {
    "site_name": "PPM Data Stack",
    "site_locale": "en",
    "allow_tracking": false
  },
  "database": {
    "engine": "postgres",
    "name": "PPM Data Warehouse",
    "details": {
      "host": "postgres",
      "port": 5432,
      "dbname": "ppm_datawarehouse",
      "user": "${DB_USER}",
      "password": "${DB_PASS}",
      "ssl": false
    },
    "auto_run_queries": true,
    "is_full_sync": true
  }
}
ENDJSON
)

  HTTP_CODE=$(curl -s -w "%{http_code}" -X POST "${MB_URL}/api/setup" \
    -H "Content-Type: application/json" \
    -d "${PAYLOAD}" -o /tmp/setup_response.json)

  if [ "$HTTP_CODE" = "200" ]; then
    echo "Setup completed successfully."
  else
    echo "WARNING: Setup API returned HTTP $HTTP_CODE. Metabase may already be configured or password rejected."
    cat /tmp/setup_response.json 2>/dev/null || true
  fi
fi

# Now login and ensure database connection exists
echo "Verifying database connection..."
SESSION=$(curl -s -X POST "${MB_URL}/api/session" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")

if [ -z "$SESSION" ]; then
  echo "WARNING: Could not authenticate with admin credentials."
  echo "Metabase is running at http://localhost:3000 — set up manually."
  echo "Default credentials: ${ADMIN_EMAIL} / ${ADMIN_PASSWORD}"
  exit 0
fi

EXISTING=$(curl -s -X GET "${MB_URL}/api/database" \
  -H "X-Metabase-Session: $SESSION")

if echo "$EXISTING" | python3 -c "import json,sys; dbs=json.load(sys.stdin)['data']; exit(0 if any(d['name']=='PPM Data Warehouse' for d in dbs) else 1)" 2>/dev/null; then
  echo "Database connection already exists."
else
  echo "Adding PPM Data Warehouse database connection..."
  DB_PAYLOAD=$(cat <<ENDJSON
{
  "engine": "postgres",
  "name": "PPM Data Warehouse",
  "details": {
    "host": "postgres",
    "port": 5432,
    "dbname": "ppm_datawarehouse",
    "user": "${DB_USER}",
    "password": "${DB_PASS}",
    "ssl": false
  },
  "auto_run_queries": true,
  "is_full_sync": true
}
ENDJSON
)

  HTTP_CODE=$(curl -s -w "%{http_code}" -X POST "${MB_URL}/api/database" \
    -H "X-Metabase-Session: $SESSION" \
    -H "Content-Type: application/json" \
    -d "${DB_PAYLOAD}" -o /tmp/db_response.json)

  if [ "$HTTP_CODE" = "200" ]; then
    echo "Database connection configured."
  else
    echo "WARNING: Database API returned HTTP $HTTP_CODE."
    cat /tmp/db_response.json 2>/dev/null || true
  fi
fi

echo "Metabase auto-setup complete."
echo "Login at http://localhost:3000 as ${ADMIN_EMAIL} / ${ADMIN_PASSWORD}"
