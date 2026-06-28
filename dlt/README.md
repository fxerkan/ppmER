# DLT Jira Pipeline for PPM Data Stack

This directory contains the dlt (Data Load Tool) pipelines for extracting data from Jira and loading it into PostgreSQL.

## What is dlt?

dlt is a modern, Python-based EL (Extract-Load) tool that:
- **Automatic Schema Evolution**: Handles schema changes (new fields, type changes) automatically
- **Intelligent Write Modes**: Supports replace, merge, and append modes
- **Built-in State Management**: Tracks pipeline state for incremental loading

## Pipeline Architecture

### Unified Script Design

The scripts in this directory use a **unified script pattern** - each script handles both initial and daily loads through a `--mode` parameter. This eliminates code duplication and simplifies maintenance.

Key features:
- **Custom API calls**: Direct HTTP requests to Jira REST API with authentication
- **Custom flattening**: Data is manually flattened to reduce nested tables
- **Schema evolution handling**: Custom logic for table creation and schema changes
- **Detailed logging**: Comprehensive logging for debugging and monitoring in Mage

## Available Pipelines

### Unified Load Scripts (Initial/Daily via --mode)

All scripts are located in `/dlt/jira/` and support both modes:

| Script | Description | Table | Mode Behavior |
|--------|-------------|-------|---------------|
| `jira_projects.py` | Project metadata | `raw_jira.projects` | replace (both modes) |
| `jira_project_properties.py` | Portfolio properties | `raw_jira.project_properties` | replace (both modes) |
| `jira_users.py` | User accounts | `raw_jira.users` | replace (both modes) |
| `jira_issues.py` | All/updated issues | `raw_jira.issues` | initial: replace, daily: merge |
| `jira_issue_links.py` | Issue relationships | `raw_jira.issue_links` | replace (both modes) |
| `jira_issue_subtasks.py` | Subtask relationships | `raw_jira.issue_subtasks` | replace (both modes) |
| `jira_worklogs.py` | Time tracking | `raw_jira.worklogs` | initial: replace, daily: merge |
| `jira_hr_users.py` | HR user data | `raw_jira.hr_users` | replace (both modes) |
| `jira_pbb_issues.py` | Budget issues | `raw_jira.pbb_issues` | initial: replace, daily: merge |

### Usage Examples

```bash
# Initial load (full data extraction)
python jira/jira_projects.py --mode=initial
python jira/jira_issues.py --mode=initial

# Daily load (incremental/merge)
python jira/jira_projects.py --mode=daily
python jira/jira_issues.py --mode=daily
```

## Running Pipelines

### Option 1: Docker (Recommended for Production)

Run inside the DLT container:

```bash
# Run a specific pipeline with mode
docker exec ppm-dlt python jira/jira_projects.py --mode=daily

# Run multiple pipelines in sequence
docker exec ppm-dlt bash -c "python jira/jira_projects.py --mode=daily && python jira/jira_issues.py --mode=daily"

# Enter the container for interactive work
docker exec -it ppm-dlt bash
```

### Option 2: Mage AI (Recommended for Scheduling)

The pipelines are integrated with Mage AI:

1. **master_initial_jira**: Full data load with all scripts in initial mode
2. **master_daily_jira**: Incremental load with all scripts in daily mode

Both pipelines:
- Load Jira data via DLT
- Run dbt transformations (staging -> core -> mart)
- Execute data tests
- Generate documentation

### Option 3: Local Development

Use the helper script to run pipelines locally:

```bash
cd dlt

# First-time setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run a pipeline
./run_local.sh jira/jira_projects.py --mode=daily

# Or manually
source venv/bin/activate
source ../.env
python jira/jira_projects.py --mode=daily
```

## Schema Evolution

This implementation includes **automatic schema evolution** handling:

### How it works

1. **Table Existence Check**: Before loading, check if destination table exists
2. **Dynamic Write Disposition**:
   - Table exists: Uses configured mode (`merge` or `replace`)
   - Table missing: Uses `replace` mode to create the table
3. **DLT State Sync**: Reset DLT state when tables are manually dropped

### Why is this needed?

Standard dlt with `merge` mode expects the table to exist. Our custom logic handles:
1. Detecting missing tables
2. Resetting DLT pipeline state
3. Switching to `replace` mode for table creation
4. Subsequent runs use configured mode normally

## Configuration

### Environment Variables (`.env`)

```bash
# Jira Configuration
JIRA_SUBDOMAIN="https://your-domain.atlassian.net"
JIRA_EMAIL="your-email@company.com"
JIRA_API_TOKEN="your-api-token"

# Date Configuration
JIRA_START_DATE=2024-01-01T00:00:00Z    # For initial loads
JIRA_INCREMENTAL_DAYS=30                 # Days to look back for daily loads

# PostgreSQL (Docker internal)
POSTGRES_HOST=postgres
POSTGRES_DB=ppm_datawarehouse
POSTGRES_USER=ppm_user
POSTGRES_PASSWORD=ppm_password
POSTGRES_EXTERNAL_PORT=15432
```

### DLT Configuration (`.dlt/`)

- `config.toml` - General dlt settings (nesting levels, workers)
- `secrets.toml` - Credentials for local development (NOT used in Docker)

## Data Destination

All data is loaded into PostgreSQL in the `raw_jira` schema:

| Table | Description | Primary Key |
|-------|-------------|-------------|
| `projects` | Project metadata | `id` |
| `project_properties` | Portfolio properties | `project_id + property_key` |
| `users` | User accounts | `account_id` |
| `issues` | Main issues (flattened) | `id` |
| `issue_links` | Issue relationships | `_dlt_id` |
| `issue_subtasks` | Parent-child relationships | `_dlt_id` |
| `worklogs` | Time tracking entries | `id` |
| `hr_users` | HR user data | `issue_id` |
| `pbb_issues` | Budget issues | `id` |

## dbt Transformation Layers

After DLT loads raw data, dbt transforms it through three layers:

### Staging (`staging` schema)
- Views on raw tables with cleaning/renaming
- Tags: `staging`, `jira`

### Core (`core` schema)
- **Dimensions**: `dim_users`, `dim_projects`, `dim_issues`, `dim_date`
- **Facts**: `fact_issues`, `fact_worklogs`, `fact_project_budget`, `fact_worklogs_snapshot`
- **Bridge**: `map_issue_links`, `map_issue_subtasks`
- Tags: `core`, `jira`, `dim`/`fact`/`map`

### Mart (`mart` schema)
- **Aggregates**: `agg_project_health`, `mart_portfolio_dashboard`
- Tags: `mart`, `datamart`

## Monitoring & Debugging

### Check pipeline state

```bash
docker exec ppm-dlt python -c "
import dlt
p = dlt.pipeline(pipeline_name='jira_projects', destination='postgres')
print(p.state)
"
```

### View container logs

```bash
docker logs ppm-dlt
```

### Check database tables

```bash
docker exec ppm-postgres psql -U ppm_user -d ppm_datawarehouse -c "\dt raw_jira.*"
```

### Check row counts

```bash
docker exec ppm-postgres psql -U ppm_user -d ppm_datawarehouse -c "
SELECT
    schemaname,
    relname as table,
    n_tup_ins as inserts,
    n_tup_upd as updates
FROM pg_stat_user_tables
WHERE schemaname = 'raw_jira'
ORDER BY relname;
"
```

## Utility Modules

### `dlt_utils.py`

Shared utilities for schema evolution:

```python
from dlt_utils import (
    get_postgres_connection,     # Get DB connection (Docker or local)
    table_exists,                # Check if table exists
    sync_dlt_state_with_database, # Reset DLT state for missing tables
    determine_write_disposition,  # Choose merge vs replace
    run_pipeline_with_schema_evolution  # Full pipeline runner
)
```

### `run_local.sh`

Helper script to run pipelines locally:
- Loads environment variables from `.env`
- Activates virtual environment
- Runs the specified pipeline with arguments

## Troubleshooting

### "relation does not exist" error

This happens when using `merge` mode on a deleted table:
1. The script should auto-detect and use `replace` mode
2. If not, manually reset the pipeline state:
   ```python
   import dlt
   pipeline = dlt.pipeline(pipeline_name='...', destination='postgres')
   pipeline.drop()
   ```

### "Credentials not configured" (local)

1. Ensure `.env` file exists in project root
2. Run using `./run_local.sh script.py` which loads env vars
3. Or manually: `source ../.env && python script.py`

### "Could not connect to postgres" (local)

1. Ensure Docker containers are running: `docker ps`
2. Check external port in `.env`: `POSTGRES_EXTERNAL_PORT=15432`
3. Verify `.dlt/secrets.toml` uses correct port for local access

## DLT Dashboard (Web UI)

A Streamlit-based dashboard is available:

```bash
# Start the dashboard (runs on port 8501)
docker exec -d ppm-dlt streamlit run /app/dashboard.py --server.port=8501 --server.address=0.0.0.0

# Access at: http://localhost:8501
```

### Dashboard Features

- **Overview**: Summary of all tables, row counts, schema structure
- **Tables**: Explore individual table schemas and sample data
- **Load History**: View DLT load operations history
- **Query**: Run custom SQL queries against the raw_jira schema

## Documentation

- dlt Documentation: https://dlthub.com/docs
- Schema Evolution: https://dlthub.com/docs/general-usage/schema-evolution
- Schema Contracts: https://dlthub.com/docs/general-usage/schema-contracts
- dlt Dashboard: https://dlthub.com/docs/general-usage/dashboard
