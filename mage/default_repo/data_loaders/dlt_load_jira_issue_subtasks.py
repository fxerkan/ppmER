"""
Mage Data Loader: Jira Issue Subtasks via DLT (OPTIMIZED)

Target: raw_jira.issue_subtasks

Uses the optimized version with:
- Connection pooling
- 8 parallel workers (configurable)
- Parallel subtask extraction
- Real-time progress metrics
"""

import sys
sys.path.insert(0, '/home/src/default_repo')

from utils.dlt_runner import run_dlt_script

if 'data_loader' not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@data_loader
def load_jira_issue_subtasks_via_dlt(data, *args, **kwargs):
    """Load Jira issue subtasks via DLT."""
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
        script_path='/home/dlt/jira/jira_issue_subtasks_optimized.py',
        target_table='raw_jira.issue_subtasks',
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
