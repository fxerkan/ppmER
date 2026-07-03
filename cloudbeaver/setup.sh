#!/bin/sh
# CB role-based setup — idempotent, safe to re-run
# ponytail: CB 24.2 uses query{} not mutation{} for admin ops
#           cbadmin is auto-created from CB_ADMIN_NAME/CB_ADMIN_PASSWORD env vars on first start
#           cloudbeaver.conf starts with anonymousAccessEnabled:true so login works on fresh start
set -e

apk add --no-cache curl postgresql-client >/dev/null 2>&1

PG="PGPASSWORD=$POSTGRES_PASSWORD psql -h postgres -U $POSTGRES_USER -d $POSTGRES_DB -v ON_ERROR_STOP=0"

# ── PostgreSQL role users ────────────────────────────────────────────────────
echo "[cb-setup] Creating PostgreSQL role users..."

eval "$PG" <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='ppm_analyst') THEN
    CREATE USER ppm_analyst WITH PASSWORD '$PG_ANALYST_PASSWORD';
  END IF;
END \$\$;
GRANT CONNECT ON DATABASE $POSTGRES_DB TO ppm_analyst;
GRANT USAGE ON SCHEMA core, mart TO ppm_analyst;
GRANT SELECT ON ALL TABLES IN SCHEMA core TO ppm_analyst;
GRANT SELECT ON ALL TABLES IN SCHEMA mart TO ppm_analyst;
ALTER DEFAULT PRIVILEGES IN SCHEMA core GRANT SELECT ON TABLES TO ppm_analyst;
ALTER DEFAULT PRIVILEGES IN SCHEMA mart GRANT SELECT ON TABLES TO ppm_analyst;
ALTER ROLE ppm_analyst SET search_path = mart, core;

DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='ppm_power_user') THEN
    CREATE USER ppm_power_user WITH PASSWORD '$PG_POWER_USER_PASSWORD';
  END IF;
END \$\$;
GRANT CONNECT ON DATABASE $POSTGRES_DB TO ppm_power_user;
GRANT USAGE ON SCHEMA raw_jira, staging, core, mart TO ppm_power_user;
GRANT SELECT ON ALL TABLES IN SCHEMA raw_jira TO ppm_power_user;
GRANT SELECT ON ALL TABLES IN SCHEMA staging TO ppm_power_user;
GRANT SELECT ON ALL TABLES IN SCHEMA core TO ppm_power_user;
GRANT SELECT ON ALL TABLES IN SCHEMA mart TO ppm_power_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA raw_jira GRANT SELECT ON TABLES TO ppm_power_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA staging GRANT SELECT ON TABLES TO ppm_power_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA core GRANT SELECT ON TABLES TO ppm_power_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA mart GRANT SELECT ON TABLES TO ppm_power_user;
ALTER ROLE ppm_power_user SET search_path = mart, core, staging;
SQL

echo "[cb-setup] PostgreSQL users ready"

# ── Wait for CloudBeaver ─────────────────────────────────────────────────────
echo "[cb-setup] Waiting for CloudBeaver..."
until curl -sf -o /dev/null -X POST http://cloudbeaver:8978/cb/api/gql \
    -H "Content-Type: application/json" \
    -d '{"query":"{ serverConfig { version } }"}'; do
  sleep 5
done
echo "[cb-setup] CloudBeaver is up"

GQL="http://cloudbeaver:8978/cb/api/gql"
JAR="/tmp/cb.jar"

# ── Open session & login as cbadmin ──────────────────────────────────────────
# ponytail: CB 24.2 creates cbadmin from CB_ADMIN_NAME/CB_ADMIN_PASSWORD env vars on first boot
#           anonymousAccessEnabled:true in cloudbeaver.conf allows session open before anon is disabled
curl -sf -c $JAR -X POST $GQL \
    -H "Content-Type: application/json" \
    -d '{"query":"mutation { openSession { valid } }"}' >/dev/null

curl -sf -b $JAR -c $JAR -X POST $GQL \
    -H "Content-Type: application/json" \
    -d "{\"query\":\"{authLogin(provider:\\\"local\\\",credentials:{user:\\\"$CB_ADMIN_NAME\\\",password:\\\"$CB_ADMIN_PASSWORD\\\"},linkUser:false){authStatus}}\"}" >/dev/null

echo "[cb-setup] Logged into CB as $CB_ADMIN_NAME"

# ── Disable anonymous access ──────────────────────────────────────────────────
curl -sf -b $JAR -X POST $GQL -H "Content-Type: application/json" \
    -d '{"query":"{configureServer(configuration:{serverName:\"ppmER\",serverURL:\"http://localhost:18978\",anonymousAccessEnabled:false})}"}' >/dev/null || true
echo "[cb-setup] Anonymous access disabled"

# ── CB teams (created by initial-data.conf, this is idempotent) ──────────────
curl -sf -b $JAR -X POST $GQL -H "Content-Type: application/json" \
    -d '{"query":"{createTeam(teamId:\"analyst_team\",teamName:\"Analysts\",description:\"Read-only core and mart\"){teamId}}"}' \
    >/dev/null || true
curl -sf -b $JAR -X POST $GQL -H "Content-Type: application/json" \
    -d '{"query":"{createTeam(teamId:\"power_user_team\",teamName:\"Power Users\",description:\"Full read ppm_datawarehouse\"){teamId}}"}' \
    >/dev/null || true
echo "[cb-setup] CB teams ready"

# ── CB users ─────────────────────────────────────────────────────────────────
curl -sf -b $JAR -X POST $GQL -H "Content-Type: application/json" \
    -d '{"query":"{createUser(userId:\"cb_analyst\",enabled:true,authRole:\"user\"){userId}}"}' >/dev/null || true
curl -sf -b $JAR -X POST $GQL -H "Content-Type: application/json" \
    -d '{"query":"{createUser(userId:\"cb_power_user\",enabled:true,authRole:\"user\"){userId}}"}' >/dev/null || true

curl -sf -b $JAR -X POST $GQL -H "Content-Type: application/json" \
    -d "{\"query\":\"{setUserCredentials(userId:\\\"cb_analyst\\\",providerId:\\\"local\\\",credentials:{password:\\\"$CB_ANALYST_PASSWORD\\\"})}\"}" >/dev/null
curl -sf -b $JAR -X POST $GQL -H "Content-Type: application/json" \
    -d "{\"query\":\"{setUserCredentials(userId:\\\"cb_power_user\\\",providerId:\\\"local\\\",credentials:{password:\\\"$CB_POWER_USER_PASSWORD\\\"})}\"}" >/dev/null

curl -sf -b $JAR -X POST $GQL -H "Content-Type: application/json" \
    -d '{"query":"{grantUserTeam(userId:\"cb_analyst\",teamId:\"analyst_team\")}"}' >/dev/null || true
curl -sf -b $JAR -X POST $GQL -H "Content-Type: application/json" \
    -d '{"query":"{grantUserTeam(userId:\"cb_power_user\",teamId:\"power_user_team\")}"}' >/dev/null || true

echo "[cb-setup] CB users ready"

# ── Connection access control ─────────────────────────────────────────────────
# ponytail: CB 24.2 uses projectId="g_GlobalConfiguration" (not "GlobalConfiguration")
curl -sf -b $JAR -X POST $GQL -H "Content-Type: application/json" \
    -d '{"query":"{setConnectionSubjectAccess(projectId:\"g_GlobalConfiguration\",connectionId:\"postgresql-container\",subjects:[\"admin\"])}"}' >/dev/null || true
curl -sf -b $JAR -X POST $GQL -H "Content-Type: application/json" \
    -d '{"query":"{setConnectionSubjectAccess(projectId:\"g_GlobalConfiguration\",connectionId:\"postgresql-analyst\",subjects:[\"analyst_team\"])}"}' >/dev/null || true
curl -sf -b $JAR -X POST $GQL -H "Content-Type: application/json" \
    -d '{"query":"{setConnectionSubjectAccess(projectId:\"g_GlobalConfiguration\",connectionId:\"postgresql-power-user\",subjects:[\"power_user_team\",\"admin\"])}"}' >/dev/null || true

echo "[cb-setup] Connection access control applied"
echo "[cb-setup] Done ✓"
