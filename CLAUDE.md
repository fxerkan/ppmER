# PPM Data Stack - AI Agent Guide

This is a Jira-based Project & Portfolio Management (PPM) data stack.

## Quick Reference

- **Postgres**: localhost:15432, db=ppm_datawarehouse
- **Mage AI**: http://localhost:6789
- **dbt Docs**: http://localhost:8081
- **CloudBeaver**: http://localhost:8978
- **Metabase**: http://localhost:3000
- **Chat Agent**: http://localhost:7860

## Tech Stack

- **dlt** — data ingestion from Jira API -> PostgreSQL
- **Mage AI** — pipeline orchestration
- **dbt** — data transformation (staging -> core -> marts)
- **Metabase** — BI dashboards
- **CloudBeaver** — SQL browser
- **PostgreSQL** — data warehouse

## Data Model (3-layer)

```
Jira API
   | dlt
raw_jira (schema)          <- raw tables
   | dbt staging
staging schema             <- cleaned views
   | dbt core
core schema                <- dim_* and fact_* tables
   | dbt marts
mart schema                <- business-ready aggregations
```

## Common Tasks

### Run a full pipeline
```bash
docker exec ppm-mage mage run default_repo master_daily_jira
```

### Run dbt models
```bash
docker exec ppm-dlt dbt run --project-dir /dbt --profiles-dir /dbt
docker exec ppm-dlt dbt run --select staging --project-dir /dbt --profiles-dir /dbt
docker exec ppm-dlt dbt run --select core --project-dir /dbt --profiles-dir /dbt
docker exec ppm-dlt dbt run --select marts --project-dir /dbt --profiles-dir /dbt
```

### Query the database
```bash
docker exec ppm-postgres psql -U ppm_user -d ppm_datawarehouse -c "SELECT * FROM mart.mart_portfolio_dashboard LIMIT 10"
```

## MCP Server (for Claude Code / Cursor)

Add to your MCP config:
```json
{
  "mcpServers": {
    "ppm-data-stack": {
      "command": "python",
      "args": ["./agent/mcp_server.py"],
      "env": {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "15432",
        "POSTGRES_DB": "ppm_datawarehouse",
        "POSTGRES_USER": "ppm_user",
        "POSTGRES_PASSWORD": "your_password"
      }
    }
  }
}
```

## Key dbt Models

| Layer | Model | Description |
|-------|-------|-------------|
| staging | stg_jira__issues | All Jira issues |
| staging | stg_jira__worklogs | All time logs |
| core | dim_projects | Project dimension |
| core | dim_users | User dimension |
| core | fact_worklogs | Worklog fact table with historical snapshots |
| core | fact_issues | Issue fact table |
| marts | mart_portfolio_dashboard | Portfolio overview |
| marts | agg_project_health | Project health metrics |
| marts | rpt_missing_effort | Issues with missing time logs |

---

## Agent Skills

When working with any component of this stack, reference the relevant skill file:

| Tool | Skill file | When to use |
|------|-----------|-------------|
| dbt | `skills/dbt-skill.md` | Creating/editing dbt models, debugging dbt errors, running dbt |
| dlt | `skills/dlt-skill.md` | Creating/editing dlt pipelines, debugging data load errors |
| Mage AI | `skills/mage-skill.md` | Creating pipelines, scheduling, debugging orchestration |
| Metabase | `skills/metabase-skill.md` | Creating dashboards, connecting data, debugging BI |

Always read the relevant skill file before modifying code for that tool.

## Agent Personas

This repo ships with pre-configured agent modes. Use them in your AI assistant:

**dbt-agent**: "You are a dbt expert for the PPM Data Stack. Before any action, read `skills/dbt-skill.md`. Apply naming conventions strictly. Run `dbt compile` before `dbt run` to catch errors early."

**dlt-agent**: "You are a dlt pipeline expert for the PPM Data Stack. Before any action, read `skills/dlt-skill.md`. Always validate that raw data loaded correctly before triggering dbt."

**mage-agent**: "You are a Mage AI orchestration expert for the PPM Data Stack. Before any action, read `skills/mage-skill.md`. Check pipeline dependencies before making changes."

**ppm-analyst**: "You are a PPM data analyst. Use `query_db` tool to explore data. Focus only on `mart.*` and `core.*` schemas. Read `skills/metabase-skill.md` for dashboard work."
