"""
Mage Data Loader: Jira HR Users via DLT

Target: raw_jira.hr_users
"""

import sys
sys.path.insert(0, '/home/src/default_repo')

from utils.dlt_runner import run_dlt_script

if 'data_loader' not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@data_loader
def load_jira_hr_users_via_dlt(*args, **kwargs):
    """Load Jira HR users via DLT."""
    pipeline_type = kwargs.get('pipeline_type')
    if not pipeline_type:
        config = kwargs.get('configuration', {})
        pipeline_type = config.get('pipeline_type')
    if not pipeline_type:
        pipeline_type = 'initial'

    print(f"Pipeline Type: {pipeline_type}")

    # Get pipeline name for notifications
    pipeline_uuid = kwargs.get('pipeline_uuid', 'master_daily_jira')

    result = run_dlt_script(
        script_path='/home/dlt/jira/jira_hr_users.py',
        target_table='raw_jira.hr_users',
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
