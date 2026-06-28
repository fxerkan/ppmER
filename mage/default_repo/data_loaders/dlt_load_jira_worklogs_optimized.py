"""
Mage Data Loader: Jira Worklogs via DLT (OPTIMIZED)

Target: raw_jira.worklogs

This optimized version uses multi-threaded parallel processing for significantly
faster worklog extraction compared to the standard version.

Performance:
- 8x faster issue worklog fetching
- Configurable worker count via pipeline variables
- Real-time performance metrics

Usage in Mage:
    1. Add pipeline variable: max_workers (default: 8)
    2. Add pipeline variable: pipeline_type (initial or daily)
    3. Run the data loader

Example Pipeline Variables:
    {
        "pipeline_type": "initial",
        "max_workers": 8
    }
"""

import sys
sys.path.insert(0, '/home/src/default_repo')

from utils.dlt_runner import run_dlt_script

if 'data_loader' not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@data_loader
def load_jira_worklogs_via_dlt_optimized(data, *args, **kwargs):
    """
    Load Jira worklogs via DLT using optimized multi-threaded extraction.

    Pipeline Variables:
        - pipeline_type: 'initial' or 'daily' (default: 'initial')
        - max_workers: Number of parallel workers (default: 8)

    Worker Configuration Guidelines:
        - Conservative (avoid rate limits): 4 workers
        - Balanced (default): 8 workers
        - Aggressive (high throughput): 16 workers
        - Very Aggressive (maximum speed): 32 workers

    Performance:
        - Standard version: ~5-10 issues/sec
        - Optimized version: ~40-80 issues/sec (8 workers)
    """
    # Get pipeline configuration
    pipeline_type = kwargs.get('pipeline_type')
    max_workers = kwargs.get('max_workers')

    # Fallback to configuration if not in kwargs
    if not pipeline_type or not max_workers:
        config = kwargs.get('configuration', {})
        if not pipeline_type:
            pipeline_type = config.get('pipeline_type')
        if not max_workers:
            max_workers = config.get('max_workers')

    # Set defaults
    if not pipeline_type:
        pipeline_type = 'initial'
    if not max_workers:
        max_workers = 8

    # Validate max_workers
    try:
        max_workers = int(max_workers)
        if max_workers < 1:
            max_workers = 8
        if max_workers > 64:
            print(f"Warning: max_workers={max_workers} is very high, may hit API rate limits")
    except (ValueError, TypeError):
        print(f"Warning: Invalid max_workers value '{max_workers}', using default 8")
        max_workers = 8

    print("=" * 80)
    print("Jira Worklogs DLT Load (OPTIMIZED)")
    print("=" * 80)
    print(f"Pipeline Type: {pipeline_type}")
    print(f"Max Workers: {max_workers}")
    print(f"Script: /home/dlt/jira/jira_worklogs_optimized.py")
    print("=" * 80)

    # Build extra arguments
    extra_args = [
        f'--mode={pipeline_type}',
        f'--max-workers={max_workers}'
    ]

    # Get pipeline name for notifications
    pipeline_uuid = kwargs.get('pipeline_uuid', 'master_daily_jira')

    # Worklogs extraction - uses chunked loading with parallel processing
    result = run_dlt_script(
        script_path='/home/dlt/jira/jira_worklogs_optimized.py',
        target_table='raw_jira.worklogs',
        fail_on_error=True,
        timeout=1800,  # 30 minutes - should be sufficient even for large loads
        extra_args=extra_args,
        pipeline_name=pipeline_uuid,
    )

    # Add metadata to result
    result['pipeline_type'] = pipeline_type
    result['max_workers'] = max_workers
    result['optimization'] = 'parallel_multi_threaded'

    return result


@test
def test_output(output, *args) -> None:
    """Validate the output of the data loader."""
    assert output is not None, 'The output is undefined'
    assert output.get('status') == 'success', f"Load failed: {output}"

    # Optional: Validate optimization metadata
    assert output.get('max_workers') is not None, 'max_workers metadata missing'
    assert output.get('optimization') == 'parallel_multi_threaded', 'Optimization flag missing'
