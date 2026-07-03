"""
Mage Data Loader: Jira Issues via DLT (Async/Parallel)

Target: raw_jira.issues

Loads all Jira issues using parallel extraction with merge/upsert strategy.
"""

import sys
sys.path.insert(0, '/home/src/default_repo')

from utils.dlt_runner import run_dlt_script

if 'data_loader' not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@data_loader
def load_jira_issues_async(*args, **kwargs):
    pipeline_type = kwargs.get('pipeline_type')
    if not pipeline_type:
        config = kwargs.get('configuration', {})
        pipeline_type = config.get('pipeline_type', 'daily')

    pipeline_uuid = kwargs.get('pipeline_uuid', 'master_daily_jira')
    print(f"[issues_async] pipeline_type={pipeline_type}")

    result = run_dlt_script(
        script_path='/home/dlt/jira/jira_issues.py',
        target_table='raw_jira.issues',
        fail_on_error=True,
        extra_args=[f'--mode={pipeline_type}'],
        pipeline_name=pipeline_uuid,
    )
    result['pipeline_type'] = pipeline_type
    return result


@test
def test_output(output, *args) -> None:
    assert output is not None, 'The output is undefined'
    assert output.get('status') == 'success', f"Load failed: {output}"
