"""
Pipeline Monitor Utility

Monitors pipeline execution times and detects stuck pipelines.
Uses Mage.ai's database to track pipeline run history and calculate expected durations.

Features:
- Tracks pipeline execution history
- Calculates average/expected execution times
- Detects stuck pipelines based on configurable multiplier
- Sends notifications for stuck pipelines
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default expected durations (in minutes) for pipelines
# These are used as fallbacks when no history is available
DEFAULT_EXPECTED_DURATIONS = {
    'jira_issues': 30,
    'jira_worklogs': 60,
    'master_daily_jira': 45,
    'master_initial_jira': 180,
}

# Path to store pipeline duration history
DURATION_HISTORY_FILE = '/home/src/mage_data/pipeline_durations.json'


def load_duration_history() -> Dict[str, List[float]]:
    """Load pipeline duration history from JSON file."""
    try:
        if os.path.exists(DURATION_HISTORY_FILE):
            with open(DURATION_HISTORY_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load duration history: {e}")
    return {}


def save_duration_history(history: Dict[str, List[float]]) -> None:
    """Save pipeline duration history to JSON file."""
    try:
        os.makedirs(os.path.dirname(DURATION_HISTORY_FILE), exist_ok=True)
        with open(DURATION_HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        logger.error(f"Could not save duration history: {e}")


def record_pipeline_duration(pipeline_name: str, duration_minutes: float) -> None:
    """
    Record a successful pipeline execution duration.

    Args:
        pipeline_name: Name of the pipeline
        duration_minutes: Execution duration in minutes
    """
    history = load_duration_history()

    if pipeline_name not in history:
        history[pipeline_name] = []

    # Keep last 20 executions for averaging
    history[pipeline_name].append(duration_minutes)
    history[pipeline_name] = history[pipeline_name][-20:]

    save_duration_history(history)
    logger.info(f"Recorded duration for {pipeline_name}: {duration_minutes:.2f} minutes")


def get_expected_duration(pipeline_name: str) -> float:
    """
    Get the expected duration for a pipeline based on historical data.

    Args:
        pipeline_name: Name of the pipeline

    Returns:
        Expected duration in minutes
    """
    history = load_duration_history()

    if pipeline_name in history and len(history[pipeline_name]) >= 3:
        # Use average of last 10 successful runs
        recent_durations = history[pipeline_name][-10:]
        avg_duration = sum(recent_durations) / len(recent_durations)
        logger.info(f"Expected duration for {pipeline_name}: {avg_duration:.2f} minutes (based on {len(recent_durations)} runs)")
        return avg_duration

    # Fall back to default
    default = DEFAULT_EXPECTED_DURATIONS.get(pipeline_name, 30)
    logger.info(f"Using default duration for {pipeline_name}: {default} minutes")
    return default


def get_stuck_threshold_multiplier() -> float:
    """Get the stuck pipeline threshold multiplier from environment."""
    return float(os.getenv('STUCK_PIPELINE_MULTIPLIER', '2.0'))


def check_pipeline_stuck(
    pipeline_name: str,
    start_time: datetime,
    current_time: Optional[datetime] = None,
) -> Tuple[bool, float, float]:
    """
    Check if a pipeline appears to be stuck.

    Args:
        pipeline_name: Name of the pipeline
        start_time: When the pipeline started
        current_time: Current time (defaults to now)

    Returns:
        Tuple of (is_stuck, current_duration_minutes, expected_duration_minutes)
    """
    current_time = current_time or datetime.now()
    duration = current_time - start_time
    current_duration_minutes = duration.total_seconds() / 60

    expected_duration = get_expected_duration(pipeline_name)
    threshold_multiplier = get_stuck_threshold_multiplier()
    threshold_minutes = expected_duration * threshold_multiplier

    is_stuck = current_duration_minutes >= threshold_minutes

    if is_stuck:
        logger.warning(
            f"Pipeline {pipeline_name} appears stuck: "
            f"running for {current_duration_minutes:.0f} minutes, "
            f"expected ~{expected_duration:.0f} minutes (threshold: {threshold_minutes:.0f} minutes)"
        )

    return is_stuck, current_duration_minutes, expected_duration


def get_running_pipelines_from_db() -> List[Dict]:
    """
    Get currently running pipelines from Mage's PostgreSQL database.

    Returns:
        List of running pipeline dictionaries with keys:
        - pipeline_uuid
        - execution_date
        - status
        - current_block (if available)
    """
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        # Get database connection URL from environment
        db_url = os.getenv('MAGE_DATABASE_CONNECTION_URL')
        if not db_url:
            logger.error("MAGE_DATABASE_CONNECTION_URL not set")
            return []

        # Parse the connection URL
        # Format: postgresql://user:password@host:port/database
        import re
        match = re.match(r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', db_url)
        if not match:
            logger.error(f"Could not parse database URL: {db_url}")
            return []

        user, password, host, port, database = match.groups()

        conn = psycopg2.connect(
            host=host,
            port=int(port),
            database=database,
            user=user,
            password=password
        )

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Query for running pipeline runs
            # Note: Table name may vary depending on Mage version
            cur.execute("""
                SELECT
                    pipeline_uuid,
                    execution_date,
                    status,
                    created_at,
                    id as run_id,
                    block_runs_count,
                    completed_block_runs_count
                FROM pipeline_run
                WHERE status = 'running'
                ORDER BY created_at DESC
            """)
            results = cur.fetchall()

        conn.close()
        return [dict(r) for r in results]

    except ImportError:
        logger.warning("psycopg2 not available, cannot query Mage database")
        return []
    except Exception as e:
        logger.error(f"Error querying Mage database: {e}")
        return []


def check_all_running_pipelines() -> List[Dict]:
    """
    Check all running pipelines for stuck status.

    Returns:
        List of stuck pipeline information dictionaries
    """
    running_pipelines = get_running_pipelines_from_db()
    stuck_pipelines = []

    for pipeline in running_pipelines:
        pipeline_name = pipeline.get('pipeline_uuid')
        start_time = pipeline.get('created_at') or pipeline.get('execution_date')

        if not pipeline_name or not start_time:
            continue

        # Ensure start_time is a datetime object
        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))

        is_stuck, current_duration, expected_duration = check_pipeline_stuck(
            pipeline_name, start_time
        )

        if is_stuck:
            stuck_pipelines.append({
                'pipeline_name': pipeline_name,
                'pipeline_uuid': pipeline_name,
                'start_time': start_time,
                'current_duration_minutes': current_duration,
                'expected_duration_minutes': expected_duration,
                'run_id': pipeline.get('run_id'),
                'block_progress': f"{pipeline.get('completed_block_runs_count', 0)}/{pipeline.get('block_runs_count', '?')}",
            })

    return stuck_pipelines


def send_stuck_alerts(stuck_pipelines: List[Dict]) -> int:
    """
    Send email alerts for stuck pipelines.

    Args:
        stuck_pipelines: List of stuck pipeline information

    Returns:
        Number of alerts sent
    """
    from utils.email_notifier import send_pipeline_stuck_notification

    alerts_sent = 0

    for pipeline in stuck_pipelines:
        success = send_pipeline_stuck_notification(
            pipeline_name=pipeline['pipeline_name'],
            pipeline_uuid=pipeline['pipeline_uuid'],
            start_time=pipeline['start_time'],
            current_duration_minutes=pipeline['current_duration_minutes'],
            expected_duration_minutes=pipeline['expected_duration_minutes'],
            threshold_multiplier=get_stuck_threshold_multiplier(),
            run_id=pipeline.get('run_id'),
            current_block=pipeline.get('block_progress'),
        )

        if success:
            alerts_sent += 1
            logger.info(f"Sent stuck alert for pipeline: {pipeline['pipeline_name']}")
        else:
            logger.error(f"Failed to send stuck alert for pipeline: {pipeline['pipeline_name']}")

    return alerts_sent


# File to track sent stuck alerts (to avoid duplicate notifications)
SENT_ALERTS_FILE = '/home/src/mage_data/sent_stuck_alerts.json'


def load_sent_alerts() -> Dict[str, str]:
    """Load the record of sent stuck alerts."""
    try:
        if os.path.exists(SENT_ALERTS_FILE):
            with open(SENT_ALERTS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load sent alerts record: {e}")
    return {}


def save_sent_alerts(alerts: Dict[str, str]) -> None:
    """Save the record of sent stuck alerts."""
    try:
        os.makedirs(os.path.dirname(SENT_ALERTS_FILE), exist_ok=True)
        with open(SENT_ALERTS_FILE, 'w') as f:
            json.dump(alerts, f, indent=2)
    except Exception as e:
        logger.error(f"Could not save sent alerts record: {e}")


def cleanup_old_alerts() -> None:
    """Remove alert records older than 24 hours."""
    alerts = load_sent_alerts()
    cutoff = datetime.now() - timedelta(hours=24)
    cutoff_str = cutoff.isoformat()

    cleaned = {k: v for k, v in alerts.items() if v > cutoff_str}
    if len(cleaned) < len(alerts):
        save_sent_alerts(cleaned)
        logger.info(f"Cleaned up {len(alerts) - len(cleaned)} old alert records")


def check_and_alert_stuck_pipelines() -> Dict:
    """
    Main function to check for stuck pipelines and send alerts.

    Tracks sent alerts to avoid duplicate notifications for the same pipeline run.

    Returns:
        Dictionary with check results
    """
    cleanup_old_alerts()

    stuck_pipelines = check_all_running_pipelines()
    sent_alerts = load_sent_alerts()

    new_stuck_pipelines = []
    for pipeline in stuck_pipelines:
        # Create a unique key for this pipeline run
        alert_key = f"{pipeline['pipeline_name']}_{pipeline.get('run_id', 'unknown')}"

        if alert_key not in sent_alerts:
            new_stuck_pipelines.append(pipeline)
            sent_alerts[alert_key] = datetime.now().isoformat()

    alerts_sent = 0
    if new_stuck_pipelines:
        alerts_sent = send_stuck_alerts(new_stuck_pipelines)
        save_sent_alerts(sent_alerts)

    return {
        'total_running': len(get_running_pipelines_from_db()),
        'stuck_count': len(stuck_pipelines),
        'new_alerts_sent': alerts_sent,
        'stuck_pipelines': [p['pipeline_name'] for p in stuck_pipelines],
    }


if __name__ == '__main__':
    # Test the monitor
    result = check_and_alert_stuck_pipelines()
    print(f"Monitor check result: {result}")
