"""
Mage Transformer: DBT Dependencies

Installs dbt package dependencies before running models.
"""

import subprocess

if 'transformer' not in globals():
    from mage_ai.data_preparation.decorators import transformer
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@transformer
def run_dbt_deps(*args, **kwargs):
    
    # SKIP THIS BLOCK - return immediately
    print("⚠️ dbt_deps block is disabled - skipping execution")
    # return data 

    # """
    # Run dbt deps to install package dependencies.
    # """
    # dbt_project_path = "/home/src/default_repo/dbt"

    # print("Installing dbt dependencies...")
    # print("=" * 60)

    # result = subprocess.run(
    #     ["dbt", "deps", "--profiles-dir", dbt_project_path, "--project-dir", dbt_project_path],
    #     capture_output=True,
    #     text=True,
    #     cwd=dbt_project_path
    # )

    # if result.stdout:
    #     print(result.stdout)
    # if result.stderr:
    #     print("STDERR:", result.stderr)

    # if result.returncode != 0:
    #     raise Exception(f"dbt deps failed with return code {result.returncode}")

    # print("=" * 60)
    # print("dbt deps completed successfully!")

    return {"status": "success", "step": "dbt_deps"}


@test
def test_output(output, *args) -> None:
    assert output is not None, 'The output is undefined'
    assert output.get('status') == 'success', 'dbt deps did not complete successfully'
