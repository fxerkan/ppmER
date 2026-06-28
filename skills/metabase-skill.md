# Metabase Skill — PPM Data Stack

## What Metabase Does

Metabase provides BI dashboards connected directly to the PPM PostgreSQL data warehouse. It is the end-user-facing layer of the stack. UI is at http://localhost:3000.

## Data Connection

Metabase connects to the `ppm_datawarehouse` database. Always use `mart.*` schema tables for dashboards — these are the business-ready aggregations produced by dbt. Do not build dashboards on `raw_jira.*` or `staging.*`.

## Key Tables for Dashboards

| Table | Schema | Use for |
|-------|--------|---------|
| `mart_portfolio_dashboard` | mart | Portfolio-level KPIs, executive summary |
| `agg_project_health` | mart | Project status summary, RAG status |
| `rpt_missing_effort` | mart | Issues without any logged time |
| `fact_worklogs` | core | Raw worklog data for time analysis |
| `dim_projects` | core | Project dimensions and attributes |
| `dim_users` | core | User dimensions, team membership |

When in doubt, prefer `mart.*` over `core.*`. Use `core.*` only when the mart table doesn't have the grain you need.

## Naming Conventions

**Questions (saved queries)**:
```
[Layer] Entity - Metric
```
Examples:
- `[Mart] Portfolio - Open Issues by Project`
- `[Mart] Team - Hours Logged This Month`
- `[Core] Worklogs - Daily Log Volume`

**Dashboards**:
```
PPM - <Audience> - <Topic>
```
Examples:
- `PPM - PMO - Portfolio Overview`
- `PPM - Dev - Team Workload`
- `PPM - Management - Sprint Progress`

## Creating Dashboards via API (Automation)

```bash
# 1. Get session token
SESSION=$(curl -s -X POST http://localhost:3000/api/session \
  -H "Content-Type: application/json" \
  -d '{"username":"admin@example.com","password":"yourpassword"}' \
  | jq -r '.id')

# 2. Create a question (saved query)
curl -X POST http://localhost:3000/api/card \
  -H "X-Metabase-Session: $SESSION" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "[Mart] Portfolio - Open Issues by Project",
    "dataset_query": {
      "type": "native",
      "native": {"query": "SELECT project_key, COUNT(*) FROM mart.mart_portfolio_dashboard WHERE status != '\''Done'\'' GROUP BY 1"},
      "database": 1
    },
    "display": "bar",
    "visualization_settings": {}
  }'

# 3. Create a dashboard and add the card
curl -X POST http://localhost:3000/api/dashboard \
  -H "X-Metabase-Session: $SESSION" \
  -H "Content-Type: application/json" \
  -d '{"name": "PPM - PMO - Portfolio Overview"}'
```

## Exporting and Importing Dashboards

To share dashboards across environments (dev → prod):
1. Admin > Export → saves as `.zip`
2. On target: Admin > Import → upload the `.zip`

This preserves all questions, dashboards, and collections but not database connections (reconfigure those after import).

## Common Errors and Fixes

### "Database not found" on first start
Metabase needs time to sync the schema on first connect. Wait 2 minutes after `docker compose up` and refresh the browser. If it persists, check that the `metabase` database exists:
```bash
docker exec ppm-postgres psql -U ppm_user -d ppm_datawarehouse -c "\l" | grep metabase
```
If missing, it should have been created by `postgres/init/01-init-schemas.sql`. Run the init script manually if needed.

### Dashboard shows stale data
Metabase caches query results. Options:
- Click the refresh icon on the dashboard
- Set cache TTL: Admin > Performance > set to 60 seconds
- Disable caching for the specific question: Question settings > Caching off

### Column not found in question
The dbt model was updated (column renamed or dropped) but Metabase hasn't re-synced. Force a sync:
Admin > Databases > select database > Sync now

### "Permission denied" accessing a table
Check Metabase user groups in Admin > People > Groups. By default all users see all databases. To restrict access, move dashboards into Collections and set Collection permissions per group.

### Slow queries
1. First check the query with `EXPLAIN ANALYZE` in CloudBeaver (http://localhost:8978)
2. If a join is missing an index, add it via a dbt `post-hook`:
   ```yaml
   # in schema.yml or dbt_project.yml
   models:
     - name: fact_worklogs
       config:
         post-hook: "CREATE INDEX IF NOT EXISTS idx_fact_worklogs_issue_id ON {{ this }} (issue_id)"
   ```
3. Re-run `dbt run --select fact_worklogs` to apply the index

### Metabase container won't start
Check that the `metabase` internal database exists in PostgreSQL:
```bash
docker logs ppm-metabase | tail -30
docker exec ppm-postgres psql -U ppm_user -c "\l"
```
The `01-init-schemas.sql` init script should create it. If the postgres container was recreated after Metabase first ran, re-run the init script.

## What NOT to Do

- Never build dashboards on `raw_jira.*` or `staging.*` — they change without notice
- Never hardcode date ranges in questions — use Metabase's relative date filters (`Past 30 days`, `This month`)
- Never store sensitive data in Metabase questions — access control is at the Collection level, not per-column
- Never use `SELECT *` in native queries — name all columns explicitly so Metabase can display them correctly
- Never delete a question that's used in a dashboard without first removing it from the dashboard
