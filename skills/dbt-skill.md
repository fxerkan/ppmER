# dbt Skill — PPM Data Stack

## Naming Conventions

| Prefix | Layer | Example |
|--------|-------|---------|
| `stg_<source>__<entity>` | Staging | `stg_jira__issues.sql` |
| `dim_<entity>` | Core | `dim_projects.sql` |
| `fact_<entity>` | Core | `fact_worklogs.sql` |
| `mart_<entity>` | Marts | `mart_portfolio_dashboard.sql` |
| `agg_<entity>` | Marts | `agg_project_health.sql` |
| `rpt_<entity>` | Marts | `rpt_missing_effort.sql` |
| `map_<entity>` | Marts | `map_status_categories.sql` |

Double underscore separates source from entity in staging: `stg_jira__issues`, `stg_sharepoint__resources`.

## Layer Rules

| Layer | Materialization | Allowed operations | Schema |
|-------|-----------------|-------------------|--------|
| Staging | view | Rename, cast, coalesce — no business logic | `staging` |
| Core | table | Joins, business logic, SCD2 lookups | `core` |
| Marts | table | Aggregations, final grain for reports | `mart` |

## Model Config Headers

```sql
-- staging
{{ config(materialized='view') }}

-- core
{{ config(materialized='table') }}

-- marts
{{ config(materialized='table') }}

-- large fact tables (incremental)
{{ config(materialized='incremental', unique_key='worklog_id') }}
```

## Source and Ref References

```sql
-- In staging models only: reference raw source tables
SELECT * FROM {{ source('raw_jira', 'issues') }}

-- Everywhere else: reference other dbt models
SELECT * FROM {{ ref('stg_jira__issues') }}
SELECT * FROM {{ ref('dim_projects') }}
```

Never use `{{ source() }}` outside staging. Never hardcode schema names like `raw_jira.issues`.

## Column Naming Rules

- All columns: `snake_case`
- Booleans: prefix `is_` or `has_` (e.g. `is_active`, `has_subtasks`)
- Timestamps: suffix `_at` (e.g. `created_at`, `updated_at`)
- Dates: suffix `_date` (e.g. `due_date`, `sprint_start_date`)
- IDs: suffix `_id` (e.g. `project_id`, `assignee_id`, `issue_id`)

## Schema YAML — Required for Every Model

Every model must have a matching entry in `schema.yml`:

```yaml
models:
  - name: fact_worklogs
    description: "One row per Jira worklog entry with resolved dimension keys."
    columns:
      - name: worklog_id
        description: "Primary key — Jira worklog ID."
        tests:
          - not_null
          - unique
      - name: issue_id
        description: "FK to dim_issues."
        tests:
          - not_null
      - name: author_id
        description: "FK to dim_users."
      - name: time_spent_seconds
        description: "Duration logged in seconds."
      - name: logged_at
        description: "Timestamp when work was logged."
```

## Tests — Minimum Requirements

For every fact table, add `not_null` and `unique` on the primary key:

```yaml
tests:
  - not_null
  - unique
```

For foreign keys in fact tables, add `not_null`. For reference columns with a fixed set of values, add `accepted_values`.

## Incremental Model Pattern

For fact tables with >100k rows:

```sql
{{ config(materialized='incremental', unique_key='worklog_id') }}

SELECT
    worklog_id,
    issue_id,
    author_id,
    time_spent_seconds,
    logged_at
FROM {{ ref('stg_jira__worklogs') }}

{% if is_incremental() %}
WHERE logged_at > (SELECT MAX(logged_at) FROM {{ this }})
{% endif %}
```

Always include the `{% if is_incremental() %}` guard — without it, the filter applies on every run including the first full load.

## Historical / Snapshot Pattern

SCD2 tables use the `_snapshot` suffix and live in `snapshots/`, not `models/`:

```sql
-- snapshots/issues_snapshot.sql
{% snapshot issues_snapshot %}

{{
    config(
        target_schema='snapshots',
        strategy='timestamp',
        unique_key='issue_id',
        updated_at='updated_at',
    )
}}

SELECT * FROM {{ source('raw_jira', 'issues') }}

{% endsnapshot %}
```

Run snapshots separately: `dbt snapshot --project-dir /dbt --profiles-dir /dbt`

## Running Commands

```bash
# Run all staging models
docker exec ppm-dbt-docs dbt run --select staging --project-dir /dbt --profiles-dir /dbt

# Run specific model and all upstream dependencies
docker exec ppm-dbt-docs dbt run --select +fact_worklogs --project-dir /dbt --profiles-dir /dbt

# Run model and all downstream dependents
docker exec ppm-dbt-docs dbt run --select fact_worklogs+ --project-dir /dbt --profiles-dir /dbt

# Compile only (catch syntax errors without running)
docker exec ppm-dbt-docs dbt compile --project-dir /dbt --profiles-dir /dbt

# Run dbt tests
docker exec ppm-dbt-docs dbt test --project-dir /dbt --profiles-dir /dbt

# Test a specific model
docker exec ppm-dbt-docs dbt test --select fact_worklogs --project-dir /dbt --profiles-dir /dbt

# Generate and serve docs
docker exec ppm-dbt-docs dbt docs generate --project-dir /dbt --profiles-dir /dbt

# Install packages (run after clone or after adding to packages.yml)
docker exec ppm-dbt-docs dbt deps --project-dir /dbt --profiles-dir /dbt
```

## Common Errors and Fixes

### `relation does not exist`
Upstream model hasn't been built yet. Run upstream first:
```bash
docker exec ppm-dbt-docs dbt run --select +this_model --project-dir /dbt --profiles-dir /dbt
```

### `column does not exist`
Raw source schema changed. Check the actual column names in CloudBeaver (http://localhost:8978) against `raw_jira` schema, then update the staging model.

### `dbt deps` needed
After cloning or adding a package to `packages.yml`, always run:
```bash
docker exec ppm-dbt-docs dbt deps --project-dir /dbt --profiles-dir /dbt
```

### Circular reference
Check the DAG to find the cycle:
```bash
docker exec ppm-dbt-docs dbt ls --select +model+ --output path --project-dir /dbt --profiles-dir /dbt
```

### `target schema not found`
`profiles.yml` target schema doesn't match the database. Check that `POSTGRES_DB` in `.env` matches the database name in `profiles.yml`.

### Incremental model returning wrong results
Missing `is_incremental()` guard. Add it:
```sql
{% if is_incremental() %}
WHERE updated_at > (SELECT MAX(updated_at) FROM {{ this }})
{% endif %}
```

## What NOT to Do

- No business logic in staging models (only rename, cast, coalesce)
- No raw table references (`raw_jira.issues`) in core or mart models — use `{{ ref() }}`
- No `SELECT *` in final mart/core models — always name columns explicitly
- No hardcoded dates — use dbt variables: `{{ var('start_date', '2020-01-01') }}`
- No duplicate column names within a CTE chain (alias them)
- No snapshots in `models/` directory — they belong in `snapshots/`
