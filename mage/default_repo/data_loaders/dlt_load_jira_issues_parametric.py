"""
Mage Data Loader: Jira Issues via DLT - PARAMETRIC VERSION

Target: raw_jira.issues

This version allows runtime variable configuration for:
- start_date: Start date for issue extraction (YYYY-MM-DD) [optional]
- end_date: End date for issue extraction (YYYY-MM-DD) [optional]
- pipeline_type: 'initial' or 'daily'

Additional optional filters for targeted extraction:
- issue_key: Filter by specific issue key (e.g., "PROJ-123")
- issue_id: Filter by specific issue ID
- issue_type: Filter by issue type name (e.g., "Bug", "Story", "Task")

Use Case:
    - Historical data migration in chunks, e.g., 2020-01 to 2025-12
    - Re-syncing missing issues for specific keys or types
    - Targeted extraction for troubleshooting

Example Runtime Variables (set in Mage UI when running):

    # Date range extraction:
    {
        "start_date": "2020-01-01",
        "end_date": "2020-03-31",
        "pipeline_type": "initial"
    }

    # Extract a specific issue:
    {
        "issue_key": "PROJ-123"
    }

    # Extract issues by type with date range:
    {
        "issue_type": "Bug",
        "start_date": "2024-01-01",
        "end_date": "2024-12-31"
    }

    # Extract issue by ID:
    {
        "issue_id": "10001"
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
def load_jira_issues_parametric(*args, **kwargs):
    """
    Load Jira issues via DLT using parametric date range and optional filters.

    Parameters are passed as command-line arguments to the DLT script.
    The script will use these values instead of .env variables.

    Runtime Variables (from Mage UI):
        Date range (optional when using filters):
        - start_date: Start date (YYYY-MM-DD format), e.g., '2020-01-01'
        - end_date: End date (YYYY-MM-DD format), e.g., '2020-03-31'

        Pipeline settings:
        - pipeline_type: 'initial' or 'daily' (default: 'initial')

        Optional filters (any combination):
        - issue_key: Filter by specific issue key (e.g., 'PROJ-123')
        - issue_id: Filter by specific issue ID
        - issue_type: Filter by issue type name (e.g., 'Bug', 'Story', 'Task')

    Returns:
        dict: Result dictionary with status and metadata
    """
    import re

    # Get parameters from runtime variables
    start_date = kwargs.get('start_date')
    end_date = kwargs.get('end_date')
    pipeline_type = kwargs.get('pipeline_type')

    # Get optional filter parameters
    issue_key = kwargs.get('issue_key')
    issue_id = kwargs.get('issue_id')
    issue_type = kwargs.get('issue_type')

    # Fallback to configuration if not in kwargs
    config = kwargs.get('configuration', {})
    if not start_date:
        start_date = config.get('start_date')
    if not end_date:
        end_date = config.get('end_date')
    if not pipeline_type:
        pipeline_type = config.get('pipeline_type')
    if not issue_key:
        issue_key = config.get('issue_key')
    if not issue_id:
        issue_id = config.get('issue_id')
    if not issue_type:
        issue_type = config.get('issue_type')

    # Determine if we have any filter parameters
    has_filters = any([issue_key, issue_id, issue_type])

    # Validate required parameters (date range only required if no filters)
    if not has_filters:
        if not start_date:
            raise ValueError("start_date is required when no filters are provided. Set it in Runtime Variables (format: YYYY-MM-DD)")
        if not end_date:
            raise ValueError("end_date is required when no filters are provided. Set it in Runtime Variables (format: YYYY-MM-DD)")

    # Set defaults for optional parameters
    if not pipeline_type:
        pipeline_type = 'initial'

    # Validate date format if dates are provided
    date_pattern = r'^\d{4}-\d{2}-\d{2}$'
    if start_date and not re.match(date_pattern, start_date):
        raise ValueError(f"Invalid start_date format: '{start_date}'. Expected: YYYY-MM-DD")
    if end_date and not re.match(date_pattern, end_date):
        raise ValueError(f"Invalid end_date format: '{end_date}'. Expected: YYYY-MM-DD")

    print("=" * 80)
    print("Jira Issues DLT Load (PARAMETRIC)")
    print("=" * 80)
    if start_date:
        print(f"Start Date: {start_date}")
    if end_date:
        print(f"End Date: {end_date}")
    print(f"Pipeline Type: {pipeline_type}")

    # Print filter parameters if any
    if has_filters:
        print("-" * 40)
        print("Active Filters:")
        if issue_key:
            print(f"  Issue Key: {issue_key}")
        if issue_id:
            print(f"  Issue ID: {issue_id}")
        if issue_type:
            print(f"  Issue Type: {issue_type}")
        print("-" * 40)

    print("=" * 80)

    # Build command-line arguments for the DLT script
    extra_args = [
        f'--mode={pipeline_type}'
    ]

    # Add date range if provided
    if start_date:
        extra_args.append(f'--start-date={start_date}')
    if end_date:
        extra_args.append(f'--end-date={end_date}')

    # Add filter parameters if provided
    if issue_key:
        extra_args.append(f'--issue-key={issue_key}')
    if issue_id:
        extra_args.append(f'--issue-id={issue_id}')
    if issue_type:
        extra_args.append(f'--issue-type={issue_type}')

    # Get pipeline name for notifications
    pipeline_uuid = kwargs.get('pipeline_uuid', 'jira_issues')

    # Run the DLT script with parameters
    result = run_dlt_script(
        script_path='/home/dlt/jira/jira_issues.py',
        target_table='raw_jira.issues',
        fail_on_error=True,
        timeout=3600,  # 1 hour - longer for historical data
        extra_args=extra_args,
        pipeline_name=pipeline_uuid,
    )

    # Add metadata to result
    if start_date:
        result['start_date'] = start_date
    if end_date:
        result['end_date'] = end_date
    result['pipeline_type'] = pipeline_type
    result['mode'] = 'filter' if has_filters else 'parametric'

    # Add filter metadata if applicable
    if issue_key:
        result['issue_key'] = issue_key
    if issue_id:
        result['issue_id'] = issue_id
    if issue_type:
        result['issue_type'] = issue_type

    return result


@test
def test_output(output, *args) -> None:
    """Validate the output of the data loader."""
    assert output is not None, 'The output is undefined'
    assert output.get('status') == 'success', f"Load failed: {output}"

    # Validate mode (either 'parametric' or 'filter')
    mode = output.get('mode')
    assert mode in ['parametric', 'filter'], f"Mode should be 'parametric' or 'filter', got: {mode}"

    # In parametric mode, date range is required
    # In filter mode, dates are optional
    if mode == 'parametric':
        assert output.get('start_date') is not None, 'start_date metadata missing in parametric mode'
        assert output.get('end_date') is not None, 'end_date metadata missing in parametric mode'
