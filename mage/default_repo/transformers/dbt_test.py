"""
Mage Transformer: DBT Tests

Runs all dbt tests to validate data quality.
"""

import subprocess

if 'transformer' not in globals():
    from mage_ai.data_preparation.decorators import transformer
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@transformer
def run_dbt_tests(data, *args, **kwargs):
    """
    Run all dbt tests to validate data quality.
    """
    dbt_project_path = "/home/src/default_repo/dbt"

    print("Running dbt tests...")
    print("=" * 60)

    result = subprocess.run(
        [
            "dbt", "test",
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

    # Parse test results
    stdout = result.stdout or ""
    passed_tests = stdout.count("PASS")
    failed_tests = stdout.count("FAIL")
    warned_tests = stdout.count("WARN")

    print("=" * 60)
    print(f"Test Results: {passed_tests} passed, {failed_tests} failed, {warned_tests} warnings")

    if result.returncode != 0:
        raise Exception(f"dbt tests failed with return code {result.returncode}")

    print("dbt tests completed successfully!")

    return {
        "status": "success",
        "step": "dbt_test",
        "passed": passed_tests,
        "failed": failed_tests,
        "warnings": warned_tests
    }


@test
def test_output(output, *args) -> None:
    assert output is not None, 'The output is undefined'
    assert output.get('status') == 'success', 'dbt tests did not complete successfully'
