# Mage AI Skill — PPM Data Stack

## What Mage AI Does

Mage AI orchestrates pipelines that call dlt scripts (data load) and dbt models (transform). It provides a UI for scheduling, monitoring, and triggering pipelines. UI is at http://localhost:6789.

## Pipeline Naming Convention

| Pattern | Purpose | Example |
|---------|---------|---------|
| `master_<scope>_<frequency>` | Orchestration pipelines | `master_daily_jira`, `master_initial_jira` |
| `master_<source>` | Source-scoped orchestration | `master_sharepoint` |
| `<source>_<entity>` | Standalone loaders | `jira_issues_loader` |
| `dbt_only_pipeline` | dbt-only runs | `dbt_only_pipeline` |

## Block Naming Convention

| Decorator | Naming pattern | Example |
|-----------|---------------|---------|
| `@data_loader` | `dlt_load_<entity>` | `dlt_load_worklogs` |
| `@transformer` | `dbt_<model_or_group>` | `dbt_staging`, `dbt_fact_worklogs` |
| `@data_exporter` | `send_<action>` | `send_email_report` |

## Block Structure

Every block is a Python function with the appropriate decorator. Always include a `@test` function:

```python
from mage_ai.data_preparation.decorators import data_loader, test
import subprocess

@data_loader
def load_jira_issues(*args, **kwargs):
    result = subprocess.run(
        ['python', '/home/dlt/jira/jira_issues.py', '--mode=daily'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise Exception(f"dlt failed: {result.stderr}")
    return result.stdout

@test
def test_output(output, *args):
    assert output is not None, 'Output must not be None'
    assert 'rows' in output.lower() or len(output) > 0, 'Expected dlt output'
```

## Pipeline YAML Structure

Each pipeline lives in `pipelines/<pipeline_name>/`:
- `pipeline.py` — Python block definitions
- `metadata.yaml` — schedule, description, tags

```yaml
# metadata.yaml
name: master_daily_jira
description: Daily load of Jira data and dbt transformation
tags:
  - jira
  - daily
schedules:
  - name: daily_at_6am
    schedule_type: time
    start_time: '2024-01-01 06:00:00'
    schedule_interval: '@daily'
    status: active
```

## How to Run a Pipeline

```bash
# Via Mage UI: http://localhost:6789
# Click on pipeline → Run pipeline now

# Via CLI inside container
docker exec ppm-mage mage run default_repo master_daily_jira

# Via API (get pipeline ID from UI first)
curl -X POST http://localhost:6789/api/pipeline_schedules/<id>/pipeline_runs \
  -H "Content-Type: application/json" \
  -d '{"pipeline_run": {"variables": {}}}'
```

## Callback Pattern for Failure Notifications

Reference `email_on_failure` in `metadata.yaml`:

```yaml
callbacks:
  - name: email_on_failure
    type: block
    block_type: callback
```

The callback block lives in `callbacks/email_on_failure.py` and uses `SMTP_*` env vars.

## Pipeline Conflict Warning

`master_initial_jira` and `master_daily_jira` both write to the same tables. Never run them simultaneously — the second will error on merge conflicts. Check that no pipeline is running before starting a full/initial load.

## Common Errors and Fixes

### Block fails with import error
The block runs in Mage's Python environment. Add the missing package to `mage/requirements.txt` and rebuild the container:
```bash
docker compose build ppm-mage && docker compose up -d ppm-mage
```

### `dlt` not found in a Mage block
The dlt scripts are in the ppm-dlt container, not ppm-mage. Either use `subprocess.run` to call the dlt container, or add this at the top of the block to point to the shared mount:
```python
import sys
sys.path.insert(0, '/home/dlt')
```

### dbt block fails
Ensure `profiles.yml` is volume-mounted at the path dbt expects. The dbt block should use:
```python
subprocess.run(['dbt', 'run', '--project-dir', '/home/src/default_repo/dbt', '--profiles-dir', '/home/src/default_repo/dbt'])
```

### Pipeline shows "queued" but never runs
`MAGE_DATABASE_CONNECTION_URL` env var may be pointing to an unhealthy postgres. Check:
```bash
docker exec ppm-mage python -c "import psycopg2; psycopg2.connect('...')"
docker logs ppm-mage | tail -20
```

### Email notifications not sending
Configure SMTP vars in `.env`:
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@email.com
SMTP_PASSWORD=your_app_password
```
Test with:
```bash
docker exec ppm-mage python -c "from mage_ai.services.email import send_email; print('ok')"
```

### Pipeline stuck / won't cancel via UI
Force-cancel via API:
```bash
# Get run ID from UI
curl -X DELETE http://localhost:6789/api/pipeline_runs/<run_id>
```

## What NOT to Do

- Never put secrets in pipeline code — use env vars
- Never skip the `@test` decorator on `@data_loader` blocks
- Never create circular dependencies between pipelines — use triggers (one pipeline triggers another), not Python imports
- Never run `master_initial_jira` while `master_daily_jira` is running — they conflict on the same tables
- Never modify `metadata.yaml` schedule while the pipeline is running — cancel it first
