"""
Email Notification Callback Block

This callback block sends email notifications when a pipeline block fails or succeeds.
Associate this callback with any block that should trigger email alerts.

Configuration:
- Set SMTP credentials in .env file
- Set pipeline-specific recipients in pipeline metadata.yaml:
  - notification_config.email_on_failure.to/cc/bcc
  - notification_config.email_on_success.to/cc/bcc
"""

if 'callback' not in globals():
    from mage_ai.data_preparation.decorators import callback

import os
import sys
import traceback
from datetime import datetime

# Add utils to path for imports
sys.path.insert(0, '/home/src/default_repo')


def extract_run_context(kwargs):
    """
    Extract run context information from callback kwargs.

    Returns:
        dict with run_id, trigger_id, trigger_name, trigger_params, start_time, end_time, blocks_executed
    """
    pipeline_run = kwargs.get('pipeline_run')
    pipeline_schedule = kwargs.get('pipeline_schedule')
    pipeline_uuid = kwargs.get('pipeline_uuid', 'unknown')

    # CRITICAL FIX: If pipeline_run is None, fetch from database using execution_partition
    if not pipeline_run:
        execution_partition = kwargs.get('execution_partition')
        if execution_partition and '/' in str(execution_partition):
            try:
                parts = str(execution_partition).split('/')
                schedule_id_from_partition = int(parts[0])

                from mage_ai.orchestration.db.models.schedules import PipelineRun
                from sqlalchemy import desc

                recent_run = PipelineRun.query.filter(
                    PipelineRun.pipeline_schedule_id == schedule_id_from_partition,
                    PipelineRun.pipeline_uuid == pipeline_uuid
                ).order_by(desc(PipelineRun.id)).first()

                if recent_run:
                    pipeline_run = recent_run
                    print(f"[EMAIL CALLBACK] Fetched pipeline_run from database: ID={recent_run.id}")
            except Exception as e:
                print(f"[EMAIL CALLBACK] Could not fetch pipeline_run: {e}")
                import traceback
                traceback.print_exc()

    context = {
        'run_id': None,
        'trigger_id': None,
        'trigger_name': None,
        'trigger_params': None,
        'execution_logs': None,
        'start_time': None,
        'end_time': None,
        'execution_duration_seconds': None,
        'blocks_executed': [],
    }

    # Extract run_id and timing info
    if pipeline_run:
        # CRITICAL: Get the numeric database ID, not execution_partition
        context['run_id'] = getattr(pipeline_run, 'id', None)

        # Get timing information
        context['start_time'] = getattr(pipeline_run, 'started_at', None)
        if not context['start_time']:
            context['start_time'] = getattr(pipeline_run, 'created_at', None)

        context['end_time'] = getattr(pipeline_run, 'completed_at', None)
        if not context['end_time']:
            context['end_time'] = getattr(pipeline_run, 'updated_at', None) or datetime.now()

        # Calculate duration
        if context['start_time']:
            try:
                if isinstance(context['start_time'], datetime):
                    end_time_calc = context['end_time'] if isinstance(context['end_time'], datetime) else datetime.now()
                    context['execution_duration_seconds'] = (end_time_calc - context['start_time']).total_seconds()
            except Exception:
                pass

        # Try to get the pipeline_schedule_id to fetch schedule info
        pipeline_schedule_id = getattr(pipeline_run, 'pipeline_schedule_id', None)

        # CRITICAL: If we have a schedule_id but no pipeline_schedule object, fetch it from database
        if pipeline_schedule_id and not pipeline_schedule:
            try:
                from mage_ai.orchestration.db.models.schedules import PipelineSchedule
                pipeline_schedule = PipelineSchedule.query.get(pipeline_schedule_id)
                print(f"[EMAIL CALLBACK] Fetched pipeline_schedule from database: ID={pipeline_schedule_id}")
            except Exception as e:
                print(f"[EMAIL CALLBACK] Warning: Could not load pipeline schedule: {e}")
                import traceback
                traceback.print_exc()

    # Extract trigger information
    if pipeline_schedule:
        context['trigger_id'] = getattr(pipeline_schedule, 'id', None)
        context['trigger_name'] = getattr(pipeline_schedule, 'name', None)

        # Get trigger variables/parameters
        context['trigger_params'] = getattr(pipeline_schedule, 'variables', None)

        # Merge with pipeline_run variables if available
        if pipeline_run:
            run_vars = getattr(pipeline_run, 'variables', None)
            if run_vars and isinstance(run_vars, dict):
                if context['trigger_params'] and isinstance(context['trigger_params'], dict):
                    # Merge both
                    context['trigger_params'] = {**context['trigger_params'], **run_vars}
                else:
                    context['trigger_params'] = run_vars

    return context


@callback('failure')
def send_failure_email(parent_block_data, **kwargs):
    """
    Send email notification when a parent block fails.

    This callback receives context about the failed block and pipeline,
    then sends a formatted email to the configured recipients.
    """
    from utils.email_notifier import send_pipeline_failure_notification

    # Extract context from kwargs
    block_uuid = kwargs.get('block_uuid', 'unknown_callback')
    parent_block_uuid = kwargs.get('parent_block_uuid', 'unknown_block')
    pipeline_uuid = kwargs.get('pipeline_uuid', 'unknown_pipeline')
    execution_date = kwargs.get('execution_date', datetime.now())
    pipeline_run = kwargs.get('pipeline_run')

    # Extract run context (run_id, trigger_id, trigger_name, logs)
    run_context = extract_run_context(kwargs)

    # Try to get error details from the pipeline run
    error_message = None
    error_traceback = None

    if pipeline_run:
        # Try to get error from pipeline run object
        error_message = getattr(pipeline_run, 'error', None)
        if not error_message:
            error_message = getattr(pipeline_run, 'message', None)

    # Get additional context
    additional_context = {
        'callback_block': block_uuid,
        'ds': kwargs.get('ds'),
        'hr': kwargs.get('hr'),
        'execution_partition': kwargs.get('execution_partition'),
    }

    # Log the failure notification attempt
    print(f"[EMAIL CALLBACK] Sending failure notification for pipeline: {pipeline_uuid}")
    print(f"[EMAIL CALLBACK] Failed block: {parent_block_uuid}")
    print(f"[EMAIL CALLBACK] Run ID: {run_context['run_id']}")
    print(f"[EMAIL CALLBACK] Trigger: {run_context['trigger_name']} (ID: {run_context['trigger_id']})")
    print(f"[EMAIL CALLBACK] Trigger Params: {run_context['trigger_params']}")
    print(f"[EMAIL CALLBACK] Start Time: {run_context['start_time']}")
    print(f"[EMAIL CALLBACK] End Time: {run_context['end_time']}")
    print(f"[EMAIL CALLBACK] Duration: {run_context['execution_duration_seconds']}")
    print(f"[EMAIL CALLBACK] Blocks Executed: {run_context['blocks_executed']}")
    print(f"[EMAIL CALLBACK] Execution date: {execution_date}")

    # Send the notification
    success = send_pipeline_failure_notification(
        pipeline_name=pipeline_uuid,
        pipeline_uuid=pipeline_uuid,
        block_name=parent_block_uuid,
        error_message=error_message,
        error_traceback=error_traceback,
        execution_date=execution_date,
        run_id=run_context['run_id'],
        trigger_id=run_context['trigger_id'],
        trigger_name=run_context['trigger_name'],
        trigger_params=run_context['trigger_params'],
        start_time=run_context['start_time'],
        end_time=run_context['end_time'],
        execution_duration_seconds=run_context['execution_duration_seconds'],
        blocks_executed=run_context['blocks_executed'],
        execution_logs=run_context['execution_logs'],
        additional_context=additional_context,
    )

    if success:
        print(f"[EMAIL CALLBACK] Failure notification sent successfully")
    else:
        print(f"[EMAIL CALLBACK] Failed to send notification email")

    return {'notification_sent': success}


@callback('success')
def send_success_email(parent_block_data, **kwargs):
    """
    Send email notification when a parent block succeeds.

    This callback sends a success notification email to configured recipients.
    Configure recipients in pipeline metadata.yaml under notification_config.email_on_success.
    """
    from utils.email_notifier import send_pipeline_success_notification

    # Extract context from kwargs
    block_uuid = kwargs.get('block_uuid', 'unknown_callback')
    parent_block_uuid = kwargs.get('parent_block_uuid', 'unknown_block')
    pipeline_uuid = kwargs.get('pipeline_uuid', 'unknown_pipeline')
    execution_date = kwargs.get('execution_date', datetime.now())

    # Extract run context (run_id, trigger_id, trigger_name, trigger_params, timing, blocks)
    run_context = extract_run_context(kwargs)

    # Log the success notification attempt
    print(f"[EMAIL CALLBACK] Block '{parent_block_uuid}' in pipeline '{pipeline_uuid}' completed successfully")
    print(f"[EMAIL CALLBACK] Run ID: {run_context['run_id']}")
    print(f"[EMAIL CALLBACK] Trigger: {run_context['trigger_name']} (ID: {run_context['trigger_id']})")
    print(f"[EMAIL CALLBACK] Trigger Params: {run_context['trigger_params']}")
    print(f"[EMAIL CALLBACK] Duration: {run_context['execution_duration_seconds']}")
    print(f"[EMAIL CALLBACK] Blocks Executed: {run_context['blocks_executed']}")

    # Use blocks from context or fallback to parent_block_uuid
    blocks_executed = run_context['blocks_executed'] if run_context['blocks_executed'] else [parent_block_uuid]

    # Send the success notification
    success = send_pipeline_success_notification(
        pipeline_name=pipeline_uuid,
        pipeline_uuid=pipeline_uuid,
        execution_date=execution_date,
        run_id=run_context['run_id'],
        trigger_id=run_context['trigger_id'],
        trigger_name=run_context['trigger_name'],
        trigger_params=run_context['trigger_params'],
        start_time=run_context['start_time'],
        end_time=run_context['end_time'],
        execution_duration_seconds=run_context['execution_duration_seconds'],
        blocks_executed=blocks_executed,
        execution_logs=run_context['execution_logs'],
    )

    if success:
        print(f"[EMAIL CALLBACK] Success notification sent successfully")
    else:
        print(f"[EMAIL CALLBACK] No success notification sent (no recipients configured or send failed)")

    return {'notification_sent': success, 'status': 'success'}
