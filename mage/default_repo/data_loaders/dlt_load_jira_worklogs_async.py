"""
Mage Data Loader: Jira Worklogs via DLT (Async/Optimized)

Target: raw_jira.worklogs

Loads all Jira worklogs using multi-threaded parallel extraction.
"""

import sys
sys.path.insert(0, '/home/src/default_repo')

from utils.dlt_runner import run_dlt_script

if 'data_loader' not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@data_loader
def load_jira_worklogs_async(data, *args, **kwargs):
    pipeline_type = kwargs.get('pipeline_type')
    if not pipeline_type:
        config = kwargs.get('configuration', {})
        pipeline_type = config.get('pipeline_type', 'daily')

    pipeline_uuid = kwargs.get('pipeline_uuid', 'master_daily_jira')
    max_workers = kwargs.get('max_workers', 8)
    print(f"[worklogs_async] pipeline_type={pipeline_type} max_workers={max_workers}")

    result = run_dlt_script(
        script_path='/home/dlt/jira/jira_worklogs_optimized.py',
        target_table='raw_jira.worklogs',
        fail_on_error=True,
        extra_args=[f'--mode={pipeline_type}', f'--max-workers={max_workers}'],
        pipeline_name=pipeline_uuid,
    )
    result['pipeline_type'] = pipeline_type
    return result


@test
def test_output(output, *args) -> None:
    assert output is not None, 'The output is undefined'
    assert output.get('status') == 'success', f"Load failed: {output}"
