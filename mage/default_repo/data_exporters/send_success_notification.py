"""
Send Success Notification Data Exporter

This block sends a success email notification when all upstream blocks complete.
Add this as the final block in a pipeline to notify on successful completion.
"""

import sys
sys.path.insert(0, '/home/src/default_repo')

from datetime import datetime

if 'data_exporter' not in globals():
    from mage_ai.data_preparation.decorators import data_exporter


@data_exporter
def send_notification(data, *args, **kwargs):
    """
    Send success email notification when pipeline completes successfully.
    """
    from utils.email_notifier import send_pipeline_success_notification, load_pipeline_metadata

    # Get pipeline info from kwargs
    pipeline_uuid = kwargs.get('pipeline_uuid', 'unknown_pipeline')
    block_uuid = kwargs.get('block_uuid', 'send_success_notification')

    # Extract run/trigger info
    pipeline_run = kwargs.get('pipeline_run')
    pipeline_schedule = kwargs.get('pipeline_schedule')

    # CRITICAL FIX: If pipeline_run is None, try to fetch it from the database
    # Mage doesn't pass pipeline_run object to data_exporter blocks by default
    # But we can get it using pipeline_uuid and execution_date/execution_partition
    if not pipeline_run:
        # Try multiple methods to get the pipeline_run
        # Method 1: Direct pipeline_run_id
        pipeline_run_id = kwargs.get('pipeline_run_id')

        # Method 2: Extract from execution_partition
        if not pipeline_run_id:
            execution_partition = kwargs.get('execution_partition')
            print(f"[FIX] execution_partition: {execution_partition}")
            if execution_partition and '/' in str(execution_partition):
                # execution_partition format: "4/20251220T183953_895057"
                # Where 4 is the schedule_id, and we need to find the run
                try:
                    parts = str(execution_partition).split('/')
                    schedule_id_from_partition = int(parts[0])
                    exec_date_str = parts[1]  # e.g. "20251220T183953_895057"

                    # Query for the most recent run with this schedule and execution date pattern
                    from mage_ai.orchestration.db.models.schedules import PipelineRun
                    from sqlalchemy import desc

                    # Find the run by schedule_id and pipeline_uuid
                    recent_run = PipelineRun.query.filter(
                        PipelineRun.pipeline_schedule_id == schedule_id_from_partition,
                        PipelineRun.pipeline_uuid == pipeline_uuid
                    ).order_by(desc(PipelineRun.id)).first()

                    if recent_run:
                        pipeline_run = recent_run
                        pipeline_run_id = recent_run.id
                        print(f"[FIX] Found pipeline_run from execution_partition: ID={pipeline_run_id}")

                        # CRITICAL: Refresh the object from database to get latest values
                        # The pipeline might still be running when this block executes
                        try:
                            from mage_ai.orchestration.db import db_connection
                            db_connection.session.refresh(pipeline_run)
                            print(f"[FIX] Refreshed pipeline_run from database")
                        except Exception as e:
                            print(f"[FIX] Could not refresh pipeline_run: {e}")
                except Exception as e:
                    print(f"[FIX] Could not parse execution_partition: {e}")
                    import traceback
                    traceback.print_exc()

        # Method 3: Use pipeline_run_id if we got it
        if pipeline_run_id and not pipeline_run:
            try:
                from mage_ai.orchestration.db.models.schedules import PipelineRun
                pipeline_run = PipelineRun.query.get(pipeline_run_id)
                print(f"[FIX] Fetched pipeline_run from database: ID={pipeline_run_id}")
            except Exception as e:
                print(f"[FIX] Warning: Could not fetch pipeline_run: {e}")
                import traceback
                traceback.print_exc()

    run_id = None
    trigger_id = None
    trigger_name = None
    trigger_params = None
    start_time = None
    end_time = None
    all_blocks_executed = []

    # Removed debug logging

    if pipeline_run:
        # Get the numeric run_id (this is the database ID)
        run_id = getattr(pipeline_run, 'id', None)

        # Get timing information
        start_time = getattr(pipeline_run, 'started_at', None)
        if not start_time:
            start_time = getattr(pipeline_run, 'created_at', None)

        end_time = getattr(pipeline_run, 'completed_at', None)
        if not end_time:
            end_time = getattr(pipeline_run, 'updated_at', None)

        # IMPORTANT: If this is a success notification running as the last block,
        # the pipeline won't be marked completed yet, so use NOW() as end_time
        # Also check if end_time is within 1 second of start_time (likely unset)
        if not end_time or (start_time and abs((end_time - start_time).total_seconds()) < 1):
            from datetime import timezone
            end_time = datetime.now(timezone.utc)
            print(f"[INFO] Using current time as end_time since pipeline is still running")

        # Try to get the pipeline_schedule_id to fetch schedule info
        pipeline_schedule_id = getattr(pipeline_run, 'pipeline_schedule_id', None)

        # If we have a schedule_id but no pipeline_schedule object, fetch it
        if pipeline_schedule_id and not pipeline_schedule:
            try:
                from mage_ai.orchestration.db.models.schedules import PipelineSchedule
                pipeline_schedule = PipelineSchedule.query.get(pipeline_schedule_id)
            except Exception as e:
                print(f"Warning: Could not load pipeline schedule: {e}")

    if pipeline_schedule:
        trigger_id = getattr(pipeline_schedule, 'id', None)
        trigger_name = getattr(pipeline_schedule, 'name', None)

        # Get trigger variables/parameters
        trigger_params = getattr(pipeline_schedule, 'variables', None)

        # Merge with pipeline_run variables if available
        if pipeline_run:
            run_vars = getattr(pipeline_run, 'variables', None)
            if run_vars and isinstance(run_vars, dict):
                if trigger_params and isinstance(trigger_params, dict):
                    # Merge both
                    trigger_params = {**trigger_params, **run_vars}
                else:
                    trigger_params = run_vars

    # Fallback run_id
    if not run_id:
        run_id = kwargs.get('execution_partition', 'manual_run')

    # Calculate execution duration
    execution_duration = None
    if start_time:
        try:
            if isinstance(start_time, datetime):
                end_time_calc = end_time if isinstance(end_time, datetime) else datetime.now()
                execution_duration = (end_time_calc - start_time).total_seconds()
        except Exception:
            pass

    # Get custom notifications config
    custom_notifications = None
    try:
        metadata = load_pipeline_metadata(pipeline_uuid)
        custom_notifications = metadata.get('custom_notifications', {})
        print(custom_notifications)
    except Exception as e:
        print(f"Warning: Could not load custom notifications config: {e}")

    # Get list of upstream blocks that completed
    # Prefer all_blocks_executed from pipeline_run, fall back to upstream_block_uuids
    if all_blocks_executed:
        blocks_executed = all_blocks_executed
    else:
        blocks_executed = kwargs.get('upstream_block_uuids', [])
        if not blocks_executed:
            blocks_executed = [block_uuid]

    print("=" * 70)
    print("SENDING SUCCESS NOTIFICATION")
    print("=" * 70)
    print(f"Pipeline: {pipeline_uuid}")
    print(f"Run ID: {run_id}")
    print(f"Trigger: {trigger_name} (ID: {trigger_id})")
    print(f"Trigger Params: {trigger_params}")
    print(f"Start Time: {start_time}")
    print(f"End Time: {end_time}")
    print(f"Duration: {execution_duration:.1f}s" if execution_duration else "Duration: N/A")
    print(f"Blocks: {', '.join(blocks_executed)}")
    print("=" * 70)

    # Send the success notification
    success = send_pipeline_success_notification(
        pipeline_name=pipeline_uuid,
        pipeline_uuid=pipeline_uuid,
        execution_date=datetime.now(),
        run_id=run_id,
        trigger_id=trigger_id,
        trigger_name=trigger_name,
        trigger_params=trigger_params,
        start_time=start_time,
        end_time=end_time,
        execution_duration_seconds=execution_duration,
        blocks_executed=blocks_executed,
        execution_logs=f"Pipeline {pipeline_uuid} completed successfully.\nAll {len(blocks_executed)} blocks executed without errors.",
        custom_notifications=custom_notifications,
    )

    if success:
        print("SUCCESS notification email sent!")
    else:
        print("WARNING: Failed to send success notification (check recipient config)")

    return {'notification_sent': success, 'status': 'success'}
