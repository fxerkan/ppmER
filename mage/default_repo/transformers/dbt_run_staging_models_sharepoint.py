"""
Mage Transformer: DBT SharePoint Staging Models

Runs all SharePoint staging models which create views on top of raw_sharepoint tables.

Models:
- stg_shrp__projects
- stg_shrp__proje_inv
- stg_shrp__proje_risks
- stg_shrp__issue_type
- stg_shrp__issue_type_inventory
- stg_shrp__pbi_info

Target Schema: staging
"""

import subprocess

if 'transformer' not in globals():
    from mage_ai.data_preparation.decorators import transformer
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@transformer
def run_dbt_sharepoint_staging_models(data, *args, **kwargs):
    """
    Run all dbt SharePoint staging models.
    These models create views in the staging schema.
    """
    dbt_project_path = "/home/src/default_repo/dbt"

    print("Running dbt SharePoint staging models...")
    print("Target: staging schema")
    print("=" * 60)

    # Run all SharePoint staging models
    result = subprocess.run(
        [
            "dbt", "run",
            "--select", "staging.sharepoint.*",
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
        raise Exception(f"dbt SharePoint staging models failed with return code {result.returncode}")

    print("=" * 60)
    print("dbt SharePoint staging models completed successfully!")

    return {
        "status": "success",
        "step": "dbt_sharepoint_staging_models",
        "models": [
            "stg_shrp__projects",
            "stg_shrp__proje_inv",
            "stg_shrp__proje_risks",
            "stg_shrp__issue_type",
            "stg_shrp__issue_type_inventory",
            "stg_shrp__pbi_info"
        ]
    }


@test
def test_output(output, *args) -> None:
    assert output is not None, 'The output is undefined'
    assert output.get('status') == 'success', 'dbt SharePoint staging models did not complete successfully'
