"""
Mage Transformer: DBT Staging Models

Runs all staging models which create views on top of raw_jira tables.
These models are independent and can run in parallel.

Jira Models:
- stg_jira__projects (with portfolio properties)
- stg_jira__users (enriched with HR data)
- stg_jira__issues
- stg_jira__issue_links
- stg_jira__issue_subtasks
- stg_jira__worklogs
- stg_jira__hr_users
- stg_jira__pbb_issues
- stg_jira__project_properties

Target Schema: staging
"""

import subprocess

if 'transformer' not in globals():
    from mage_ai.data_preparation.decorators import transformer
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@transformer
def run_dbt_staging_models(data, *args, **kwargs):
    """
    Run all dbt staging models (Jira).
    These models create views in the staging schema.
    """
    dbt_project_path = "/home/src/default_repo/dbt"

    print("Running dbt staging models (Jira)...")
    print("Target: staging schema")
    print("=" * 60)

    # Run Jira staging models
    print("\n--- Running Jira Staging Models ---")
    result_jira = subprocess.run(
        [
            "dbt", "run",
            "--select", "staging.jira.*",
            "--profiles-dir", dbt_project_path,
            "--project-dir", dbt_project_path
        ],
        capture_output=True,
        text=True,
        cwd=dbt_project_path
    )

    if result_jira.stdout:
        print(result_jira.stdout)
    if result_jira.stderr:
        print("STDERR:", result_jira.stderr)

    if result_jira.returncode != 0:
        raise Exception(f"dbt Jira staging models failed with return code {result_jira.returncode}")

    print("=" * 60)
    print("dbt staging models completed successfully!")

    return {
        "status": "success",
        "step": "dbt_staging_models",
        "models": [
            "stg_jira__projects",
            "stg_jira__users",
            "stg_jira__issues",
            "stg_jira__issue_links",
            "stg_jira__issue_subtasks",
            "stg_jira__worklogs",
            "stg_jira__hr_users",
            "stg_jira__pbb_issues",
            "stg_jira__project_properties"
        ]
    }


@test
def test_output(output, *args) -> None:
    assert output is not None, 'The output is undefined'
    assert output.get('status') == 'success', 'dbt staging models did not complete successfully'
