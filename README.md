# Jira PPM Data Stack

An open-source Project & Portfolio Management (PPM) data platform built on top of Jira. Transform your Jira data into a production-grade analytical data warehouse with automated pipelines, historical snapshots, BI dashboards, and an AI chat agent — all running locally with Docker.

**Why this exists**: Enterprise PPM tools (Planview, Clarity, etc.) cost tens of thousands per year. This stack gives you the same analytical capabilities using open-source tools, your existing Jira data, and a single `docker-compose up`.

## Architecture

```
+-------------------------------------------------------------+
|                     Jira PPM Data Stack                     |
+-------------+---------------+---------------+---------------+
|   Sources   |   Ingestion   | Transformation|   Delivery    |
+-------------+---------------+---------------+---------------+
|             |               |               |               |
|  Jira API   |     dlt       |    dbt        |   Metabase    |
|  SharePoint |   (Python)    |  (SQL models) |  Dashboards   |
|             |               |               |               |
|             |      v        |      v        |   CloudBeav.  |
|             |  Mage AI      |  PostgreSQL   |   (SQL UI)    |
|             | (orchestrate) |  Data Whouse  |               |
|             |               |               |  AI Agent     |
|             |               |               |  Chat UI      |
+-------------+---------------+---------------+---------------+
```

## Data Lineage

```
Jira API
  |
  v (dlt pipelines)
raw_jira schema       <- raw JSON-like tables (issues, worklogs, users, projects)
  |
  v (dbt staging)
staging schema        <- typed, cleaned, renamed columns
  |
  v (dbt core)
core schema           <- dim_* (dimensions) + fact_* (facts with snapshots)
  |
  v (dbt marts)
mart schema           <- business KPIs, portfolio views, exception reports
  |
  v
Metabase / CloudBeaver / AI Agent
```

## Services

| Service | URL | Purpose |
|---------|-----|---------|
| Mage AI | http://localhost:6789 | Pipeline orchestration |
| Metabase | http://localhost:3000 | BI dashboards |
| CloudBeaver | http://localhost:8978 | SQL browser |
| dbt Docs | http://localhost:8081 | Data lineage docs |
| AI Agent | http://localhost:7860 | Natural language queries |
| PostgreSQL | localhost:15432 | Data warehouse |

## Quick Start

### 1. Prerequisites

- Docker Desktop (4GB+ RAM allocated)
- Jira Cloud account with API access

### 2. Clone and configure

```bash
git clone https://github.com/fxerkan/jira-ppm-data-stack.git
cd jira-ppm-data-stack
cp .env.example .env
```

Edit `.env` with your Jira credentials:
```env
JIRA_SUBDOMAIN=your-company        # your-company.atlassian.net
JIRA_EMAIL=you@example.com
JIRA_API_TOKEN=your-api-token      # from https://id.atlassian.com/manage-profile/security/api-tokens
POSTGRES_PASSWORD=change_me_strong_password
```

### 3. Start the stack

```bash
docker-compose up -d
```

Wait ~2 minutes for all services to start. Check status:
```bash
docker-compose ps
```

### 4. Run your first data load

Open Mage AI at http://localhost:6789 and run the `master_initial_jira` pipeline for a full historical load, or `master_daily_jira` for incremental updates.

Or run from terminal:
```bash
docker exec ppm-mage mage run default_repo master_initial_jira
```

### 5. Open Metabase

Go to http://localhost:3000, complete the setup, add your PostgreSQL connection (host: `postgres`, port: `5432`, db: `ppm_datawarehouse`, user: `ppm_user`), and start building dashboards.

See [metabase/README.md](metabase/README.md) for 5 ready-to-use dashboard SQL queries.

## Why Historical Data Model?

Most Jira analytics tools only show you the current state. If an issue changed from "In Progress" to "Done" last week, you can't see when that happened or measure the velocity.

This stack uses a **snapshot-based historical data model**:

- `dim_issues_snapshot` — captures issue state changes over time (status, assignee, story points)
- `dim_projects_snapshot` — project metadata history
- `fact_worklogs` — every worklog entry, preserving history even after Jira deletions
- `fact_distributed_efforts` — distributes logged effort across calendar periods for capacity reporting

This means you can answer: "What was the status of project X three months ago?", "Who changed this issue and when?", "How much effort was logged per sprint vs estimated?"

## AI Agent

The stack includes an AI chat interface that connects to your data:

```bash
open http://localhost:7860
```

Ask questions like:
- "How many open issues does each project have?"
- "Show me the top 5 users by hours logged this month"
- "Which issues have been open for more than 30 days without any worklog?"

### Connect to Claude Code / Cursor via MCP

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

## Tech Stack

| Component | Tool | Version |
|-----------|------|---------|
| Ingestion | [dlt](https://dlthub.com) | 0.5.x |
| Orchestration | [Mage AI](https://mage.ai) | latest |
| Transformation | [dbt](https://getdbt.com) | 1.8+ |
| Data Warehouse | PostgreSQL | 15 |
| BI | [Metabase](https://metabase.com) | latest |
| SQL Browser | [CloudBeaver](https://cloudbeaver.io) | 24.2 |
| AI Agent | Gradio + OpenAI SDK | 4.x |

## Contributing

PRs welcome. Please:
1. Keep changes focused (no gold-plating)
2. Test with `docker-compose up` before submitting
3. Update relevant docs if changing data model
4. Do not commit `.env` or secrets

## License

MIT
