"""
Mage Transformer: DBT Docs Generate

Generates dbt documentation.
"""

import subprocess

if 'transformer' not in globals():
    from mage_ai.data_preparation.decorators import transformer
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@transformer
def run_dbt_docs_generate(data, *args, **kwargs):
    """
    Generate dbt documentation.
    """
    dbt_project_path = "/home/src/default_repo/dbt"

    print("Generating dbt documentation...")
    print("=" * 60)

    result = subprocess.run(
        [
            "dbt", "docs", "generate",
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
        print(f"Warning: dbt docs generate returned code {result.returncode}")
        # Don't fail the pipeline for docs generation issues
        return {
            "status": "warning",
            "step": "dbt_docs_generate",
            "message": "Documentation generation had issues but pipeline continues"
        }

    print("=" * 60)
    print("dbt documentation generated successfully!")

    return {
        "status": "success",
        "step": "dbt_docs_generate",
        "docs_path": f"{dbt_project_path}/target"
    }


@test
def test_output(output, *args) -> None:
    assert output is not None, 'The output is undefined'
    # Allow both success and warning status
    assert output.get('status') in ['success', 'warning'], 'dbt docs generate encountered an error'
