"""
Mage Transformer: DBT Core Dimension Models

Runs core dimension models only (excludes map tables).

Models (Dimensions):
- dim_calc_period
- dim_calendar
- dim_users
- dim_hr
- dim_turkish_holidays
- dim_projects
- dim_projects_snapshot
- dim_issues
- dim_issues_snapshot

Target Schema: core
"""

import subprocess
import sys

if 'transformer' not in globals():
    from mage_ai.data_preparation.decorators import transformer
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@transformer
def run_dbt_core_dim_models(data, *args, **kwargs):
    """
    Run dbt core dimension models.
    These models create dimension tables in the core schema.
    """
    dbt_project_path = "/home/src/default_repo/dbt"

    print("Running dbt core dimension models...")
    print("Target: core schema (dim models only)")
    print("=" * 60)
    sys.stdout.flush()

    # Run core dimension models using tag selector (exclude snapshots for speed)
    process = subprocess.Popen(
        [
            "dbt", "run",
            "--select", "tag:dim",
            "--exclude", "*_snapshot",
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

        return_code = process.wait(timeout=900)

    except subprocess.TimeoutExpired:
        process.kill()
        print("")
        print("=" * 60)
        print("ERROR: dbt command timed out after 900 seconds")
        print("This indicates the models are taking too long to execute.")
        print("=" * 60)
        raise Exception("dbt core dimension models timed out after 900 seconds")

    if return_code != 0:
        print("")
        print("=" * 60)
        print(f"ERROR: dbt core dimension models failed with return code {return_code}")
        print("=" * 60)
        raise Exception(f"dbt core dimension models failed with return code {return_code}")

    print("=" * 60)
    print("dbt core dimension models completed successfully!")

    return {
        "status": "success",
        "step": "dbt_core_dim_models",
        "models": [
            "dim_calc_period",
            "dim_calendar",
            "dim_users",
            "dim_hr",
            "dim_turkish_holidays",
            "dim_projects",
            "dim_issues",
        ],
        "excluded": [
            "dim_projects_snapshot",
            "dim_issues_snapshot",
        ]
    }


@test
def test_output(output, *args) -> None:
    assert output is not None, 'The output is undefined'
    assert output.get('status') == 'success', 'dbt core dimension models did not complete successfully'
