"""
Mage Transformer: DBT Manual Models

Runs all manual models which create views on top of raw_jira tables.
These models are independent and can run in parallel.

Models:
- stg_manual__calc_period

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
    Run all dbt staging models.
    These models create views in the staging schema.
    """
    dbt_project_path = "/home/src/default_repo/dbt"

    print("Running dbt manual models...")
    print("Target: staging schema")
    print("=" * 60)

    # Run all staging models
    result = subprocess.run(
        [
            "dbt", "run",
            "--select", "staging.manual.*",
            "--profiles-dir", dbt_project_path,
            "--project-dir", dbt_project_path
        ],
        capture_output=True,
        text=True,
        cwd=dbt_project_path
    )

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)

    if result.returncode != 0:
        raise Exception(f"dbt manual models failed with return code {result.returncode}")

    print("=" * 60)
    print("dbt manual models completed successfully!")

    return {
        "status": "success",
        "step": "dbt_manual_models",
        "models": [
            "stg_manual__calc_period",
        ]
    }


@test
def test_output(output, *args) -> None:
    assert output is not None, 'The output is undefined'
    assert output.get('status') == 'success', 'dbt manual models did not complete successfully'
