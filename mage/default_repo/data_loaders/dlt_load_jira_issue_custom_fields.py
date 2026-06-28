"""
Mage Data Loader: Jira Issue Custom Fields via DLT (OPTIMIZED)

This loader triggers the OPTIMIZED DLT script for Jira issue custom fields extraction.
The actual extraction logic is maintained in the DLT script to avoid duplication.

Optimization improvements:
- Parallel processing with 8 workers (vs 4)
- JSON storage (one row per issue vs flattened rows)
- 25-40x faster extraction
- DBT model unnests JSON back to flattened format

Usage: Used in master_initial_jira and master_daily_jira pipelines
Target: raw_jira.issue_custom_fields
"""

import sys
sys.path.insert(0, '/home/src/default_repo')

from utils.dlt_runner import run_dlt_script

if 'data_loader' not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@data_loader
def load_jira_issue_custom_fields_via_dlt(*args, **kwargs):
    """
    Load Jira issue custom fields by triggering the OPTIMIZED DLT extraction script.
    """
    pipeline_type = kwargs.get('pipeline_type')
    if not pipeline_type:
        config = kwargs.get('configuration', {})
        pipeline_type = config.get('pipeline_type')
    if not pipeline_type:
        pipeline_type = 'initial'

    # Get pipeline name for notifications
    pipeline_uuid = kwargs.get('pipeline_uuid', 'master_daily_jira')

    result = run_dlt_script(
        script_path='/home/dlt/jira/jira_issue_custom_fields_optimized.py',
        target_table='raw_jira.issue_custom_fields',
        fail_on_error=True,
        extra_args=[f'--mode={pipeline_type}'],
        pipeline_name=pipeline_uuid,
    )

    result['pipeline_type'] = pipeline_type
    return result


@test
def test_output(output, *args) -> None:
    """Test that the load completed successfully."""
    assert output is not None, 'The output is undefined'
    assert output.get('status') == 'success', f"Load failed: {output}"
