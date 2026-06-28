"""
Stuck Pipeline Sensor

This sensor checks for pipelines that have been running longer than expected
and sends email notifications when detected.

Runs every 5 minutes when triggered to monitor pipeline health.
"""

if 'sensor' not in globals():
    from mage_ai.data_preparation.decorators import sensor

import sys
sys.path.insert(0, '/home/src/default_repo')


@sensor
def check_stuck_pipelines(*args, **kwargs) -> bool:
    """
    Check for stuck pipelines and send notifications.

    This sensor:
    1. Queries the Mage database for running pipelines
    2. Checks if any are running longer than expected (2x normal duration)
    3. Sends email notifications for newly detected stuck pipelines
    4. Returns True to indicate successful check (always passes)

    Returns:
        True (sensor always completes successfully)
    """
    from utils.pipeline_monitor import check_and_alert_stuck_pipelines

    print("=" * 60)
    print("PIPELINE MONITOR - Checking for stuck pipelines")
    print("=" * 60)

    try:
        result = check_and_alert_stuck_pipelines()

        print(f"\nMonitor Results:")
        print(f"  - Total running pipelines: {result['total_running']}")
        print(f"  - Stuck pipelines detected: {result['stuck_count']}")
        print(f"  - New alerts sent: {result['new_alerts_sent']}")

        if result['stuck_pipelines']:
            print(f"\nStuck pipelines: {', '.join(result['stuck_pipelines'])}")
        else:
            print("\nNo stuck pipelines detected.")

        print("=" * 60)

        # Return True - sensor should always pass
        # The purpose is monitoring, not blocking
        return True

    except Exception as e:
        print(f"\nError during pipeline monitoring: {str(e)}")
        import traceback
        traceback.print_exc()

        # Return True even on error to prevent sensor from blocking
        # The error is logged for debugging
        return True


@sensor
def record_completed_duration(*args, **kwargs) -> bool:
    """
    Record the duration of a completed pipeline run.

    This can be called as a downstream sensor after pipeline completion
    to track execution times for stuck detection.

    Use runtime variables:
    - pipeline_name: Name of the completed pipeline
    - duration_minutes: Execution duration in minutes

    Returns:
        True on success
    """
    from utils.pipeline_monitor import record_pipeline_duration

    pipeline_name = kwargs.get('pipeline_name')
    duration_minutes = kwargs.get('duration_minutes')

    if pipeline_name and duration_minutes:
        record_pipeline_duration(pipeline_name, float(duration_minutes))
        print(f"Recorded duration for {pipeline_name}: {duration_minutes} minutes")
        return True
    else:
        print("Missing pipeline_name or duration_minutes in kwargs")
        return False
