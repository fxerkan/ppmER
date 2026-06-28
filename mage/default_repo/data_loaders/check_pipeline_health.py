"""
Pipeline Health Check Data Loader

This block checks the health of all active pipelines and returns a summary.
It's designed to run daily after all expected pipelines have completed.
"""

import sys
sys.path.insert(0, '/home/src/default_repo')

from datetime import datetime

if 'data_loader' not in globals():
    from mage_ai.data_preparation.decorators import data_loader


@data_loader
def check_pipeline_health(*args, **kwargs):
    """
    Check health of all active pipelines and return summary data.

    This block:
    1. Scans all pipelines for active triggers
    2. Categorizes them by schedule type
    3. Returns health check data for email notification

    Returns:
        dict: Health check results
    """
    from utils.pipeline_health_checker import check_pipeline_health

    print("=" * 70)
    print("PIPELINE HEALTH MONITOR")
    print("=" * 70)
    print(f"Check Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Run the health check
    health_data = check_pipeline_health(lookback_hours=48)

    print(f"\n✓ Found {health_data['total_active_pipelines']} active triggers")
    print(f"✓ Across {health_data['total_unique_pipelines']} unique pipelines")
    print(f"\nBreakdown:")
    print(f"  • Daily triggers: {health_data['summary']['daily_triggers']}")
    print(f"  • Hourly triggers: {health_data['summary']['hourly_triggers']}")
    print(f"  • Other triggers: {health_data['summary']['other_triggers']}")

    print("\nActive Pipelines:")
    for trigger in health_data['active_triggers']:
        print(f"  • {trigger['pipeline_name']}")
        print(f"    Trigger: {trigger['trigger_name']}")
        print(f"    Schedule: {trigger['schedule_interval']}")

    print("\n" + "=" * 70)
    print("Health check completed successfully!")
    print("=" * 70)

    return health_data
