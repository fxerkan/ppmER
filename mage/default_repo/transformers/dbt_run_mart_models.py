"""
Mage Transformer: DBT Mart Models

Runs mart models which create business-ready tables and aggregates.

Models:
- mart_portfolio_dashboard (executive portfolio view)
- agg_project_health (project health aggregates with scoring)
- financial dashboard 
Target Schema: mart
"""

import subprocess

if 'transformer' not in globals():
    from mage_ai.data_preparation.decorators import transformer
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@transformer
def run_dbt_mart_models(data, *args, **kwargs):
    """
    Run dbt mart models.
    These models create business-ready tables in the mart schema.
    """
    dbt_project_path = "/home/src/default_repo/dbt"

    print("Running dbt mart models...")
    print("Target: mart schema")
    print("=" * 60)

    # Run all mart models
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
        raise Exception(f"dbt mart models failed with return code {result.returncode}")

    print("=" * 60)
    print("dbt mart models completed successfully!")

    return {
        "status": "success",
        "step": "dbt_mart_models",
        "models": [
            "mart_portfolio_dashboard",
            "agg_project_health",
            "fact_financial_dashboard",
            "financial_dashboard_view"
        ]
    }


@test
def test_output(output, *args) -> None:
    assert output is not None, 'The output is undefined'
    assert output.get('status') == 'success', 'dbt mart models did not complete successfully'
