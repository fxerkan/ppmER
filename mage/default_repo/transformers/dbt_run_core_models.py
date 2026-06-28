"""
Mage Transformer: DBT Core Models

Runs core models which create dimension, fact, and bridge tables.

Models (Dimensions):
- dim_date (reference date dimension)
- dim_users (user dimension with HR data)
- dim_projects (project dimension with portfolio properties)
- dim_issues (issue dimension with metrics)

Models (Facts):
- fact_issues (incremental issue facts)
- fact_worklogs (incremental worklog facts)
- fact_project_budget (budget facts from PBB)
- fact_worklogs_snapshot (monthly snapshot for closed periods)

Models (Bridge/Map):
- map_issue_links (issue relationships)
- map_issue_subtasks (parent-child relationships)

Target Schema: core
"""

import subprocess
import sys

if 'transformer' not in globals():
    from mage_ai.data_preparation.decorators import transformer
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@transformer
def run_dbt_core_models(data, *args, **kwargs):
    """
    Run all dbt core models.
    These models create tables in the core schema.
    """
    dbt_project_path = "/home/src/default_repo/dbt"

    print("Running dbt core models...")
    print("Target: core schema")
    print("=" * 60)
    sys.stdout.flush()

    # Run all core models with real-time output streaming
    process = subprocess.Popen(
        [
            "dbt", "run",
            "--select", "core.jira.*",
            "--profiles-dir", dbt_project_path,
            "--project-dir", dbt_project_path
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=dbt_project_path,
        text=True,
        bufsize=1
    )

    # Stream output line by line in real-time
    try:
        for line in process.stdout:
            print(line.rstrip())
            sys.stdout.flush()

        return_code = process.wait(timeout=1200)

    except subprocess.TimeoutExpired:
        process.kill()
        print("")
        print("=" * 60)
        print("ERROR: dbt command timed out after 1200 seconds")
        print("This indicates the models are taking too long to execute.")
        print("=" * 60)
        raise Exception("dbt core models timed out after 1200 seconds")

    if return_code != 0:
        print("")
        print("=" * 60)
        print(f"ERROR: dbt core models failed with return code {return_code}")
        print("=" * 60)
        raise Exception(f"dbt core models failed with return code {return_code}")

    print("=" * 60)
    print("dbt core models completed successfully!")

    return {
        "status": "success",
        "step": "dbt_core_models",
        "models": {
            "dimensions": [
                "dim_calc_period",
                "dim_calendar",
                "dim_users",
                "dim_projects",
                "dim_projects_snapshot",
                "dim_issues",
                "dim_issues_snapshot",
            ],
            "facts": [
                "fact_issues",
                "fact_project_budget",
                "fact_worklogs",
                "fact_worklogs_snapshot"
            ],
            "bridge": [
                "map_issue_links",
                "map_issue_subtasks"
            ]
        }
    }


@test
def test_output(output, *args) -> None:
    assert output is not None, 'The output is undefined'
    assert output.get('status') == 'success', 'dbt core models did not complete successfully'
