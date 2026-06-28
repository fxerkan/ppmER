"""
Mage Data Loader: Jira Project Properties via DLT (OPTIMIZED)

This loader triggers the OPTIMIZED DLT script for Jira project properties extraction.
The optimized script uses parallel processing and is ~25-40x faster than the original.

Key Optimizations:
- Parallel processing with 8 workers
- Stores properties as JSON (no flattening)
- Reduced API calls and timeouts
- For daily mode: only processes updated projects

Usage: Used in master_initial_jira and master_daily_jira pipelines
Target: raw_jira.project_properties

Pipeline Types:
    - initial: Full table replace (all projects)
    - daily: Replace mode (only updated projects in lookback period)

Performance:
- Old script: ~60+ minutes (476 projects)
- New script: ~2.5 minutes (476 projects)
"""

import sys
sys.path.insert(0, '/home/src/default_repo')

from utils.dlt_runner import run_dlt_script

if 'data_loader' not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@data_loader
def load_jira_project_properties_via_dlt(*args, **kwargs):
    """Load Jira project properties via DLT (OPTIMIZED version)."""
    pipeline_type = kwargs.get('pipeline_type')
    if not pipeline_type:
        config = kwargs.get('configuration', {})
        pipeline_type = config.get('pipeline_type')
    if not pipeline_type:
        pipeline_type = 'initial'

    print(f"Pipeline Type: {pipeline_type}")
    # print("Using OPTIMIZED project properties script (25-40x faster)")

    # Get pipeline name for notifications
    pipeline_uuid = kwargs.get('pipeline_uuid', 'master_daily_jira')

    result = run_dlt_script(
        script_path='/home/dlt/jira/jira_project_properties_optimized.py',
        target_table='raw_jira.project_properties',
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
