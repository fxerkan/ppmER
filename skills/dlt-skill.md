# dlt Skill — PPM Data Stack

## What dlt Does

dlt (data load tool) extracts data from APIs and loads it to PostgreSQL with automatic schema management. In this stack it handles Jira API and SharePoint sources, landing raw data into PostgreSQL schemas before dbt picks it up.

## Pipeline Naming Convention

| Prefix | Source | Example |
|--------|--------|---------|
| `jira_<entity>` | Jira API | `jira_issues`, `jira_worklogs` |
| `shrp_<entity>` | SharePoint | `shrp_resources`, `shrp_capacity` |

The pipeline name determines the PostgreSQL schema prefix. `jira_issues` → data lands in `raw_jira` schema.

## Script Structure Pattern

```python
import argparse
import os
import dlt
from dlt.sources.helpers import requests

# Always: argparse for mode/date params at top
def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['daily', 'full'], default='daily')
    parser.add_argument('--start-date', type=str, default=None)
    return parser.parse_args()

# Source function with @dlt.resource decorator
@dlt.resource(write_disposition='append', primary_key='id')
def jira_issues(start_date: str = None):
    headers = {'Authorization': f"Basic {os.getenv('JIRA_TOKEN')}"}
    # paginate and yield rows
    for page in paginate(headers, start_date):
        yield page

# Pipeline definition at top level
def run_pipeline(args):
    pipeline = dlt.pipeline(
        pipeline_name='jira_issues',
        destination='postgres',
        dataset_name='raw_jira',   # maps to PostgreSQL schema
    )
    pipeline.run(jira_issues(start_date=args.start_date))

# Always guard with __main__
if __name__ == '__main__':
    args = parse_args()
    run_pipeline(args)
```

## Write Disposition Rules

| Disposition | When to use | Example table |
|-------------|-------------|---------------|
| `append` | Time-series data, worklogs, changelog events | `worklogs`, `issue_history` |
| `replace` | Small reference/lookup data that's replaced in full | `statuses`, `priorities` |
| `merge` | Entities that update in place (use with `primary_key`) | `issues`, `projects`, `users` |

For tables already containing data you want to keep, never use `replace`. Use `merge` with `primary_key` instead.

## Schema Destination

All raw data lands in:
- `raw_jira` schema — all Jira API data
- `raw_sharepoint` schema — all SharePoint data

Never write to `staging`, `core`, or `mart` schemas from dlt scripts. Those schemas are owned by dbt.

## Adding a New Data Source

1. Create `dlt/jira/jira_<entity>.py` following the pattern in `jira_issues.py`
2. Add the corresponding Mage data loader block: `mage/default_repo/data_loaders/dlt_load_jira_<entity>.py`
3. Add the block to the relevant Mage pipeline's `pipeline.py`
4. Create the staging dbt model: `dbt/models/staging/jira/stg_jira__<entity>.sql`
5. Add the source table entry to `dbt/models/staging/jira/sources.yml`

## Running Commands

```bash
# Run from within the dlt container
docker exec ppm-dlt python /app/jira/jira_issues.py --mode=daily
docker exec ppm-dlt python /app/jira/jira_issues.py --mode=full
docker exec ppm-dlt python /app/jira/jira_issues.py --start-date=2024-01-01

# Run SharePoint source
docker exec ppm-dlt python /app/sharepoint/shrp_resources.py --mode=full
```

## Common Errors and Fixes

### `ModuleNotFoundError: No module named 'dlt'`
Run `pip install -r requirements.txt` locally. In Docker, the container auto-installs on startup — wait ~60 seconds after `docker compose up` before running pipelines.

### `destination.credentials` error
Check `.env` has all required vars:
```
DESTINATION__POSTGRES__CREDENTIALS__HOST=postgres
DESTINATION__POSTGRES__CREDENTIALS__PORT=5432
DESTINATION__POSTGRES__CREDENTIALS__DATABASE=ppm_datawarehouse
DESTINATION__POSTGRES__CREDENTIALS__USERNAME=ppm_user
DESTINATION__POSTGRES__CREDENTIALS__PASSWORD=your_password
```
Inside Docker, use `POSTGRES_HOST=postgres` (not `localhost`). `localhost` only works when running the script directly on the host machine.

### API 401 Unauthorized
Jira API token has expired. Generate a new one at:
`https://id.atlassian.com/manage-profile/security/api-tokens`
Then update `JIRA_API_TOKEN` in `.env` and restart the container.

### Rate limit (429 Too Many Requests)
Jira's rate limit is ~1 req/100ms for personal accounts. Add a small sleep between paginated calls:
```python
import time
time.sleep(0.5)  # between pages
```
dlt has built-in retry logic but it doesn't always handle 429 gracefully.

### `write_disposition='replace'` is slow on large table
Switch to `merge` with a `primary_key`:
```python
@dlt.resource(write_disposition='merge', primary_key='issue_id')
def jira_issues():
    ...
```
Use `replace` only for tables with <10k rows.

### Column type mismatch after schema change
dlt infers types on first run. If source data changes types (e.g., a field that was `int` is now `str`), run with a full refresh to reset the inferred schema:
```bash
docker exec ppm-dlt python /app/jira/jira_issues.py --mode=full
```
If that doesn't fix it, drop the target table in CloudBeaver and re-run.

## What NOT to Do

- Never put credentials in code — always use `os.getenv('VAR_NAME')` and `.env`
- Never skip the `if __name__ == '__main__':` guard
- Never use `write_disposition='replace'` on tables that already have data you want to keep
- Never write directly to `staging`, `core`, or `mart` schemas — dlt owns only `raw_*` schemas
- Never hardcode the Jira base URL — read it from `os.getenv('JIRA_BASE_URL')`
