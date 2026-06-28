"""
Mage Transformer: DBT Core Fact Models

Runs core fact models only (excludes map tables).

Models (Facts):
- fact_issues
- fact_worklogs
- fact_worklogs_snapshot
- fact_project_budget
- fact_operation_efforts
- fact_distributed_efforts_adjustment
- fact_capex_opex_adjustment

Target Schema: core
"""

import subprocess
import sys

if 'transformer' not in globals():
    from mage_ai.data_preparation.decorators import transformer
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@transformer
def run_dbt_core_fact_models(data, *args, **kwargs):
    """
    Run dbt core fact models.
    These models create fact tables in the core schema.
    """
    dbt_project_path = "/home/src/default_repo/dbt"

    print("Running dbt core fact models...")
    print("Target: core schema (fact models only)")
    print("=" * 60)
    sys.stdout.flush()

    # Run core fact models using tag selector (exclude mart schema and snapshots)
    process = subprocess.Popen(
        [
            "dbt", "run",
            "--select", "tag:fact",
            "--exclude", "config.schema:mart *_snapshot",
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
        raise Exception("dbt core fact models timed out after 1200 seconds")

    if return_code != 0:
        print("")
        print("=" * 60)
        print(f"ERROR: dbt core fact models failed with return code {return_code}")
        print("=" * 60)
        raise Exception(f"dbt core fact models failed with return code {return_code}")

    print("=" * 60)
    print("dbt core fact models completed successfully!")

    return {
        "status": "success",
        "step": "dbt_core_fact_models",
        "models": [
            "fact_worklogs",
            "fact_project_budget",
        ],
        "excluded": [
            "fact_worklogs_snapshot",
            "fact_operation_efforts (mart schema)",
            "fact_distributed_efforts_adjustment (mart schema)",
            "fact_capex_opex_adjustment (mart schema)"
        ]
    }


@test
def test_output(output, *args) -> None:
    assert output is not None, 'The output is undefined'
    assert output.get('status') == 'success', 'dbt core fact models did not complete successfully'
