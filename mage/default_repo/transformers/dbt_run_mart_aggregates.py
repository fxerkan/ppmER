"""
Mage Transformer: DBT Mart Aggregates

Note: This transformer is now redundant as mart models are run by dbt_run_mart_facts.
Kept for backward compatibility but can be removed from pipeline.

The mart models (agg_project_health, mart_portfolio_dashboard) depend on
core models and are handled by the dbt_run_mart_facts transformer.

Target Schema: mart
"""

import subprocess

if 'transformer' not in globals():
    from mage_ai.data_preparation.decorators import transformer
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@transformer
def run_dbt_mart_aggregates(data, *args, **kwargs):
    """
    Run dbt aggregate models (backward compatibility).
    These models are also covered by dbt_run_mart_facts.
    """
    dbt_project_path = "/home/src/default_repo/dbt"

    print("Running dbt mart aggregate models...")
    print("Target: mart schema")
    print("=" * 60)

    # Run aggregate models
    result = subprocess.run(
        [
            "dbt", "run",
            "--select", "marts.*",
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
        raise Exception(f"dbt mart aggregates failed with return code {result.returncode}")

    print("=" * 60)
    print("dbt aggregate models completed successfully!")

    return {
        "status": "success",
        "step": "dbt_mart_aggregates",
        "models": ["agg_project_health", "mart_portfolio_dashboard"]
    }


@test
def test_output(output, *args) -> None:
    assert output is not None, 'The output is undefined'
    assert output.get('status') == 'success', 'dbt mart aggregates did not complete successfully'
