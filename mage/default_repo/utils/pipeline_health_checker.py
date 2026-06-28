"""
Pipeline Health Checker Utility

This module provides functionality to check the health of all active (enabled) pipelines
and their execution status. It's designed to run as a daily monitoring task.

Features:
- Finds all enabled pipeline triggers
- Checks last execution status
- Identifies failed pipelines
- Identifies pipelines that haven't run when expected
- Generates summary reports for email notifications
"""

import os
import yaml
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path
from croniter import croniter

# Path to pipelines directory
PIPELINES_DIR = '/home/src/default_repo/pipelines'

# Mage API base URL
MAGE_API_URL = os.getenv('DEFAULT_MAGE_BASE_URL', 'http://localhost:6789')


def get_pipeline_runs_from_db(pipeline_uuid: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get recent pipeline runs directly from Mage metadata database.

    Args:
        pipeline_uuid: Pipeline UUID
        limit: Number of recent runs to fetch

    Returns:
        List of pipeline run dictionaries
    """
    try:
        from mage_ai.orchestration.db.models.schedules import PipelineRun, PipelineSchedule
        from sqlalchemy import desc

        # Query pipeline runs with their associated schedules
        runs = PipelineRun.query.filter(
            PipelineRun.pipeline_uuid == pipeline_uuid
        ).order_by(desc(PipelineRun.id)).limit(limit).all()

        all_runs = []
        for run in runs:
            # Get associated schedule if exists
            schedule = None
            trigger_name = None
            trigger_id = None

            if run.pipeline_schedule_id:
                schedule = PipelineSchedule.query.get(run.pipeline_schedule_id)
                if schedule:
                    trigger_name = schedule.name
                    trigger_id = schedule.id

            run_dict = {
                'id': run.id,
                'pipeline_uuid': run.pipeline_uuid,
                'status': run.status,
                'created_at': run.created_at.isoformat() if run.created_at else None,
                'started_at': run.started_at.isoformat() if run.started_at else None,
                'completed_at': run.completed_at.isoformat() if run.completed_at else None,
                'trigger_name': trigger_name,
                'trigger_id': trigger_id,
                'variables': run.variables,
            }
            all_runs.append(run_dict)

        return all_runs

    except Exception as e:
        print(f"Warning: Could not fetch pipeline runs from database for {pipeline_uuid}: {e}")
        import traceback
        traceback.print_exc()
        return []


def calculate_next_run(schedule_interval: str, start_time: Optional[str] = None) -> Optional[datetime]:
    """
    Calculate next run time based on cron schedule.

    Args:
        schedule_interval: Cron expression (e.g., "0 9 * * *")
        start_time: Optional start time

    Returns:
        Next run datetime or None
    """
    try:
        # Handle @daily, @hourly, etc.
        cron_expr = schedule_interval
        if cron_expr.startswith('@'):
            cron_map = {
                '@yearly': '0 0 1 1 *',
                '@annually': '0 0 1 1 *',
                '@monthly': '0 0 1 * *',
                '@weekly': '0 0 * * 0',
                '@daily': '0 0 * * *',
                '@midnight': '0 0 * * *',
                '@hourly': '0 * * * *',
            }
            cron_expr = cron_map.get(cron_expr, '0 0 * * *')

        base_time = datetime.now()
        iter = croniter(cron_expr, base_time)
        return iter.get_next(datetime)

    except Exception as e:
        print(f"Warning: Could not calculate next run for schedule '{schedule_interval}': {e}")
        return None


def analyze_pipeline_health(pipeline_name: str, pipeline_uuid: str, schedule_interval: str,
                            trigger_name: str) -> Dict[str, Any]:
    """
    Analyze health of a single pipeline including last run status and predictions.

    Args:
        pipeline_name: Pipeline name
        pipeline_uuid: Pipeline UUID
        schedule_interval: Cron schedule
        trigger_name: Trigger name

    Returns:
        Health analysis dictionary
    """
    runs = get_pipeline_runs_from_db(pipeline_uuid, limit=5)

    analysis = {
        'pipeline_name': pipeline_name,
        'trigger_name': trigger_name,
        'schedule': schedule_interval,
        'last_run': None,
        'last_status': 'unknown',
        'last_duration': None,
        'avg_duration': None,
        'next_run': None,
        'is_late': False,
        'is_long_running': False,
        'recent_failures': 0,
    }

    if runs:
        last_run = runs[0]
        analysis['last_run'] = last_run.get('created_at')
        analysis['last_status'] = last_run.get('status', 'unknown')

        # Calculate durations
        durations = []
        failures = 0

        for run in runs:
            status = run.get('status', '').upper()
            if status == 'FAILED':
                failures += 1

            started_at = run.get('started_at')
            completed_at = run.get('completed_at')

            if started_at and completed_at:
                try:
                    start = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                    end = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
                    duration_seconds = (end - start).total_seconds()
                    durations.append(duration_seconds)
                except Exception:
                    pass

        if durations:
            analysis['last_duration'] = durations[0]
            analysis['avg_duration'] = sum(durations) / len(durations)

            # Check if last run was longer than normal (>1.5x average)
            if analysis['last_duration'] > (analysis['avg_duration'] * 1.5):
                analysis['is_long_running'] = True

        analysis['recent_failures'] = failures

    # Calculate next run
    next_run = calculate_next_run(schedule_interval)
    if next_run:
        analysis['next_run'] = next_run.isoformat()

        # Check if pipeline is late (expected to run but hasn't in the last cycle)
        if runs and analysis['last_run']:
            try:
                last_run_time = datetime.fromisoformat(analysis['last_run'].replace('Z', '+00:00'))
                # If next run is in the past and last run was before that, pipeline might be late
                if next_run < datetime.now() and last_run_time < (datetime.now() - timedelta(hours=2)):
                    analysis['is_late'] = True
            except Exception:
                pass

    return analysis


def load_pipeline_metadata(pipeline_name: str) -> Dict[str, Any]:
    """
    Load pipeline metadata from the metadata.yaml file.

    Args:
        pipeline_name: Name of the pipeline

    Returns:
        Dictionary containing pipeline metadata
    """
    metadata_path = os.path.join(PIPELINES_DIR, pipeline_name, 'metadata.yaml')

    if not os.path.exists(metadata_path):
        return {}

    try:
        with open(metadata_path, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error loading metadata for {pipeline_name}: {e}")
        return {}


def load_pipeline_triggers(pipeline_name: str) -> List[Dict[str, Any]]:
    """
    Load pipeline triggers from the triggers.yaml file.

    Args:
        pipeline_name: Name of the pipeline

    Returns:
        List of trigger dictionaries
    """
    triggers_path = os.path.join(PIPELINES_DIR, pipeline_name, 'triggers.yaml')

    if not os.path.exists(triggers_path):
        return []

    try:
        with open(triggers_path, 'r') as f:
            data = yaml.safe_load(f)
            return data.get('triggers', []) if data else []
    except Exception as e:
        print(f"Error loading triggers for {pipeline_name}: {e}")
        return []


def get_all_pipelines() -> List[str]:
    """
    Get list of all pipeline names.

    Returns:
        List of pipeline directory names
    """
    if not os.path.exists(PIPELINES_DIR):
        return []

    pipelines = []
    for item in os.listdir(PIPELINES_DIR):
        item_path = os.path.join(PIPELINES_DIR, item)
        # Check if it's a directory and has metadata.yaml
        if os.path.isdir(item_path):
            metadata_path = os.path.join(item_path, 'metadata.yaml')
            if os.path.exists(metadata_path):
                pipelines.append(item)

    return sorted(pipelines)


def get_active_pipeline_triggers() -> List[Dict[str, Any]]:
    """
    Get all active (enabled) pipeline triggers across all pipelines.

    Returns:
        List of dictionaries with pipeline and trigger information
    """
    active_triggers = []

    for pipeline_name in get_all_pipelines():
        triggers = load_pipeline_triggers(pipeline_name)
        metadata = load_pipeline_metadata(pipeline_name)

        for trigger in triggers:
            # Check if trigger is enabled (status: active)
            trigger_status = trigger.get('status', 'inactive')

            if trigger_status == 'active':
                active_triggers.append({
                    'pipeline_name': pipeline_name,
                    'pipeline_uuid': metadata.get('uuid', pipeline_name),
                    'trigger_name': trigger.get('name', 'unknown'),
                    'trigger_id': trigger.get('id'),
                    'schedule_type': trigger.get('schedule_type', 'time'),
                    'schedule_interval': trigger.get('schedule_interval', '@daily'),
                    'start_time': trigger.get('start_time'),
                    'variables': trigger.get('variables', {}),
                    'metadata': metadata,
                })

    return active_triggers


def check_pipeline_health(
    lookback_hours: int = 48,
    mage_api_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Check health of all active pipelines with detailed analysis.

    This function examines all active pipeline triggers and fetches their
    execution history from the Mage API to provide health analysis.

    Args:
        lookback_hours: How many hours back to check for pipeline runs
        mage_api_url: Optional Mage API URL for fetching run history

    Returns:
        Dictionary with health check results including detailed analysis
    """
    active_triggers = get_active_pipeline_triggers()

    # Analyze each pipeline
    pipeline_analyses = []
    failed_count = 0
    late_count = 0
    long_running_count = 0

    for trigger in active_triggers:
        analysis = analyze_pipeline_health(
            pipeline_name=trigger['pipeline_name'],
            pipeline_uuid=trigger['pipeline_uuid'],
            schedule_interval=trigger['schedule_interval'],
            trigger_name=trigger['trigger_name']
        )
        pipeline_analyses.append(analysis)

        if analysis['last_status'] == 'failed':
            failed_count += 1
        if analysis['is_late']:
            late_count += 1
        if analysis['is_long_running']:
            long_running_count += 1

    result = {
        'check_time': datetime.now(),
        'total_active_pipelines': len(active_triggers),
        'total_unique_pipelines': len(set(t['pipeline_name'] for t in active_triggers)),
        'active_triggers': active_triggers,
        'pipeline_analyses': pipeline_analyses,
        'summary': {
            'daily_triggers': 0,
            'hourly_triggers': 0,
            'other_triggers': 0,
            'failed_pipelines': failed_count,
            'late_pipelines': late_count,
            'long_running_pipelines': long_running_count,
        },
        'pipelines_by_schedule': {},
    }

    # Categorize triggers by schedule
    for trigger in active_triggers:
        schedule = trigger['schedule_interval']

        if '@daily' in schedule or '0 0 *' in schedule:
            result['summary']['daily_triggers'] += 1
        elif '@hourly' in schedule or '0 *' in schedule:
            result['summary']['hourly_triggers'] += 1
        else:
            result['summary']['other_triggers'] += 1

        # Group by schedule
        if schedule not in result['pipelines_by_schedule']:
            result['pipelines_by_schedule'][schedule] = []
        result['pipelines_by_schedule'][schedule].append({
            'pipeline': trigger['pipeline_name'],
            'trigger': trigger['trigger_name'],
        })

    return result


def format_duration(seconds: Optional[float]) -> str:
    """Format duration in seconds to human-readable format."""
    if seconds is None:
        return "N/A"

    minutes = int(seconds // 60)
    secs = int(seconds % 60)

    if minutes > 60:
        hours = minutes // 60
        minutes = minutes % 60
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


def format_health_report_html(health_data: Dict[str, Any]) -> str:
    """
    Format health check data as HTML for email notification with detailed analysis.

    Args:
        health_data: Health check results from check_pipeline_health()

    Returns:
        HTML formatted string
    """
    check_time = health_data['check_time'].strftime('%Y-%m-%d %H:%M:%S UTC')

    # Build pipeline analysis table
    analysis_table = ""
    for analysis in health_data.get('pipeline_analyses', []):
        status = analysis['last_status']
        status_color = {
            'completed': '#28a745',
            'failed': '#dc3545',
            'running': '#ffc107',
            'unknown': '#6c757d'
        }.get(status, '#6c757d')

        # Warning indicators
        warnings = []
        if analysis['is_late']:
            warnings.append('⚠ LATE')
        if analysis['is_long_running']:
            warnings.append('🐌 SLOW')
        if analysis['recent_failures'] > 0:
            warnings.append(f'❌ {analysis["recent_failures"]} recent failures')

        warning_text = ' '.join(warnings) if warnings else ''

        # Format times
        last_run_time = 'Never'
        if analysis['last_run']:
            try:
                dt = datetime.fromisoformat(analysis['last_run'].replace('Z', '+00:00'))
                last_run_time = dt.strftime('%Y-%m-%d %H:%M')
            except:
                last_run_time = analysis['last_run']

        next_run_time = 'N/A'
        if analysis['next_run']:
            try:
                dt = datetime.fromisoformat(analysis['next_run'])
                next_run_time = dt.strftime('%Y-%m-%d %H:%M')
            except:
                next_run_time = analysis['next_run']

        analysis_table += f"""
        <tr>
            <td>{analysis['pipeline_name']}</td>
            <td>{analysis['trigger_name']}</td>
            <td><span style="color: {status_color}; font-weight: bold;">{status.upper()}</span></td>
            <td>{last_run_time}</td>
            <td>{next_run_time}</td>
            <td>{format_duration(analysis['last_duration'])}</td>
            <td>{format_duration(analysis['avg_duration'])}</td>
            <td style="color: #dc3545; font-weight: bold;">{warning_text}</td>
        </tr>
        """

    # Build schedule breakdown table
    schedule_table = ""
    for schedule, pipelines in sorted(health_data['pipelines_by_schedule'].items()):
        schedule_table += f"<tr><td><strong>{schedule}</strong></td><td>"
        pipeline_list = "<ul>"
        for p in pipelines:
            pipeline_list += f"<li>{p['pipeline']} (Trigger: {p['trigger']})</li>"
        pipeline_list += "</ul>"
        schedule_table += f"{pipeline_list}</td></tr>"

    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 900px; margin: 0 auto; padding: 20px; }}
            .header {{ background-color: #2196F3; color: white; padding: 20px; border-radius: 5px 5px 0 0; }}
            .content {{ background-color: #f8f9fa; padding: 20px; border: 1px solid #dee2e6; }}
            .summary-box {{ background-color: #e3f2fd; border: 1px solid #2196F3; border-radius: 5px; padding: 15px; margin: 15px 0; }}
            .info-table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
            .info-table th {{ background-color: #2196F3; color: white; padding: 10px; text-align: left; }}
            .info-table td {{ padding: 10px; border-bottom: 1px solid #dee2e6; }}
            .footer {{ text-align: center; padding: 15px; color: #6c757d; font-size: 12px; }}
            ul {{ margin: 5px 0; padding-left: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>📊 Pipeline Health Monitor Report</h2>
            </div>
            <div class="content">
                <div class="summary-box">
                    <h3>Summary</h3>
                    <ul>
                        <li><strong>Check Time:</strong> {check_time}</li>
                        <li><strong>Total Active Triggers:</strong> {health_data['total_active_pipelines']}</li>
                        <li><strong>Unique Pipelines:</strong> {health_data['total_unique_pipelines']}</li>
                        <li><strong>Daily Triggers:</strong> {health_data['summary']['daily_triggers']}</li>
                        <li><strong>Hourly Triggers:</strong> {health_data['summary']['hourly_triggers']}</li>
                        <li><strong>Other Triggers:</strong> {health_data['summary']['other_triggers']}</li>
                        <li style="color: #dc3545;"><strong>Failed Pipelines:</strong> {health_data['summary']['failed_pipelines']}</li>
                        <li style="color: #ffc107;"><strong>Late Pipelines:</strong> {health_data['summary']['late_pipelines']}</li>
                        <li style="color: #ff9800;"><strong>Long Running Pipelines:</strong> {health_data['summary']['long_running_pipelines']}</li>
                    </ul>
                </div>

                <h3>Active Pipelines by Schedule</h3>
                <table class="info-table">
                    <thead>
                        <tr>
                            <th>Schedule</th>
                            <th>Pipelines</th>
                        </tr>
                    </thead>
                    <tbody>
                        {schedule_table}
                    </tbody>
                </table>

                <h3>Pipeline Health Status & Predictions</h3>
                <table class="info-table">
                    <thead>
                        <tr>
                            <th>Pipeline</th>
                            <th>Trigger</th>
                            <th>Status</th>
                            <th>Last Run</th>
                            <th>Next Run</th>
                            <th>Last Duration</th>
                            <th>Avg Duration</th>
                            <th>Warnings</th>
                        </tr>
                    </thead>
                    <tbody>
                        {analysis_table}
                    </tbody>
                </table>
            </div>
            <div class="footer">
                <p>This is an automated health check report from Mage.ai Pipeline Monitoring</p>
                <p>PPM Data Stack - {datetime.now().strftime('%Y')}</p>
            </div>
        </div>
    </body>
    </html>
    """

    return html


def format_health_report_text(health_data: Dict[str, Any]) -> str:
    """
    Format health check data as plain text for email notification.

    Args:
        health_data: Health check results from check_pipeline_health()

    Returns:
        Plain text formatted string
    """
    check_time = health_data['check_time'].strftime('%Y-%m-%d %H:%M:%S UTC')

    text = f"""
PIPELINE HEALTH MONITOR REPORT
===============================

Summary:
--------
Check Time: {check_time}
Total Active Triggers: {health_data['total_active_pipelines']}
Unique Pipelines: {health_data['total_unique_pipelines']}
Daily Triggers: {health_data['summary']['daily_triggers']}
Hourly Triggers: {health_data['summary']['hourly_triggers']}
Other Triggers: {health_data['summary']['other_triggers']}

Active Pipelines by Schedule:
------------------------------
"""

    for schedule, pipelines in sorted(health_data['pipelines_by_schedule'].items()):
        text += f"\n{schedule}:\n"
        for p in pipelines:
            text += f"  - {p['pipeline']} (Trigger: {p['trigger']})\n"

    text += "\n\nAll Active Triggers:\n"
    text += "--------------------\n"

    for trigger in health_data['active_triggers']:
        text += f"\nPipeline: {trigger['pipeline_name']}\n"
        text += f"  Trigger: {trigger['trigger_name']}\n"
        text += f"  Schedule: {trigger['schedule_interval']}\n"
        text += f"  Start Time: {trigger.get('start_time', 'N/A')}\n"

    text += f"""
---
This is an automated health check report from Mage.ai Pipeline Monitoring
PPM Data Stack - {datetime.now().strftime('%Y')}
"""

    return text


if __name__ == '__main__':
    # Test the health checker
    print("Testing Pipeline Health Checker...")
    print("=" * 70)

    health_data = check_pipeline_health()

    print(f"\nFound {health_data['total_active_pipelines']} active triggers")
    print(f"across {health_data['total_unique_pipelines']} unique pipelines\n")

    print("Summary:")
    print(f"  Daily triggers: {health_data['summary']['daily_triggers']}")
    print(f"  Hourly triggers: {health_data['summary']['hourly_triggers']}")
    print(f"  Other triggers: {health_data['summary']['other_triggers']}")

    print("\nActive Pipelines:")
    for trigger in health_data['active_triggers']:
        print(f"  - {trigger['pipeline_name']} ({trigger['trigger_name']}) - {trigger['schedule_interval']}")
