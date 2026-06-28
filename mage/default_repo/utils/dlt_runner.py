"""
DLT Script Runner Utility for Mage AI

This module provides a robust way to execute DLT scripts from Mage pipelines
with proper error detection, real-time log streaming, and handling.

Usage in data loaders:
    from utils.dlt_runner import run_dlt_script

    @data_loader
    def load_data(*args, **kwargs):
        return run_dlt_script(
            script_path='/home/dlt/jira/jira_projects.py',
            target_table='raw_jira.projects',
            extra_args=['--mode=initial']
        )
"""

import subprocess
import sys
import logging
import json
import os
import time
import traceback
from datetime import datetime
from typing import Dict, Any, Optional, List

# Get Mage logger for proper log level display
logger = logging.getLogger(__name__)

# Error indicators to look for in output (case-insensitive substring match)
# These patterns will match if they appear ANYWHERE in the log line
# IMPORTANT: Keep this list minimal to avoid false positives
ERROR_INDICATORS = [
    'traceback',
    'fatal',
    'critical',
    'databaseterminalexception',
    'databaseundefinedrelation',
    'notnullviolation',
    'violates not-null constraint',
    'integrityerror',
    'operationalerror',
    'programmingerror',
    'connection refused',
    'permission denied',
    'access denied',
    'unauthorized',
]

# Warning indicators (log but don't fail) - case-insensitive
WARNING_INDICATORS = [
    'warning',
    'deprecat',
    'futurewarning',
]

# Patterns to EXCLUDE from error detection (false positives)
ERROR_EXCLUSIONS = [
    'error_count',
    'error count',
    'errors found: 0',
    'no errors',
    'without error',
    'fail_on_error',
    'timeout:',  # Config line like "Timeout: 1800 seconds"
    'has_failed_jobs',
    'if load_info.has_failed',
    '[warn]',  # Our handled warning prefix
    '[info]',  # Info level prefix
    'skipping',  # Skipped but handled items
    'recovered',  # Recovered from error
    'retrying',  # Retry in progress
    'retry',  # Retry related
    'max retries',  # Config output
    'max_retries',  # Config output
    'status_forcelist',  # Retry config
    'timed out',  # Timeout messages (handled by retry)
    'read timeout',  # Timeout messages
    'connection pool',  # Pool messages
    'httpconnectionpool',  # Pool messages
    'httpsconnectionpool',  # Pool messages
]


def contains_indicator(line: str, indicators: List[str], exclusions: List[str] = None) -> bool:
    """
    Check if line contains any of the indicators (case-insensitive).
    Returns False if line matches any exclusion pattern.
    """
    line_lower = line.lower()

    # Check exclusions first
    if exclusions:
        for excl in exclusions:
            if excl.lower() in line_lower:
                return False

    # Check indicators
    for indicator in indicators:
        if indicator.lower() in line_lower:
            return True

    return False

# Path for DLT execution logs (for Streamlit dashboard)
DLT_LOGS_DIR = '/home/dlt/logs'


def save_execution_log(
    script_path: str,
    target_table: str,
    status: str,
    return_code: int,
    errors: List[str],
    warnings: List[str],
    output_lines: int,
    duration_seconds: float
) -> str:
    """Save execution log to JSON file for dashboard tracking."""
    try:
        os.makedirs(DLT_LOGS_DIR, exist_ok=True)

        timestamp = datetime.now()
        log_id = timestamp.strftime('%Y%m%d_%H%M%S')
        script_name = os.path.basename(script_path).replace('.py', '')
        log_filename = f"{log_id}_{script_name}.json"
        log_path = os.path.join(DLT_LOGS_DIR, log_filename)

        log_entry = {
            "id": log_id,
            "timestamp": timestamp.isoformat(),
            "script_path": script_path,
            "script_name": script_name,
            "target_table": target_table,
            "status": status,
            "return_code": return_code,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors[:20],  # Limit stored errors
            "warnings": warnings[:10],
            "output_lines": output_lines,
            "duration_seconds": round(duration_seconds, 2),
        }

        with open(log_path, 'w') as f:
            json.dump(log_entry, f, indent=2)

        return log_path
    except Exception as e:
        logger.warning(f"Failed to save execution log: {e}")
        return ""


def send_failure_notification(
    script_path: str,
    target_table: str,
    pipeline_name: str,
    errors: List[str],
    return_code: int,
    duration_seconds: float,
    extra_args: Optional[List[str]] = None,
) -> bool:
    """
    Send email notification for DLT script failure.

    Args:
        script_path: Path to the failed script
        target_table: Target table name
        pipeline_name: Name of the pipeline
        errors: List of error messages
        return_code: Script return code
        duration_seconds: Execution duration
        extra_args: Extra arguments passed to the script

    Returns:
        True if notification sent successfully
    """
    try:
        from utils.email_notifier import send_pipeline_failure_notification

        error_summary = '\n'.join(errors[:20])  # First 20 errors
        additional_context = {
            'script_path': script_path,
            'target_table': target_table,
            'return_code': return_code,
            'duration_seconds': f"{duration_seconds:.1f}s",
            'arguments': ' '.join(extra_args) if extra_args else 'none',
        }

        success = send_pipeline_failure_notification(
            pipeline_name=pipeline_name,
            pipeline_uuid=pipeline_name,
            block_name=os.path.basename(script_path).replace('.py', ''),
            error_message=error_summary[:500],  # Truncate for email
            error_traceback='\n'.join(errors[:50]),  # More errors in traceback
            execution_date=datetime.now(),
            additional_context=additional_context,
        )

        if success:
            logger.info(f"Failure notification sent for pipeline: {pipeline_name}")
        else:
            logger.warning(f"Failed to send notification for pipeline: {pipeline_name}")

        return success
    except Exception as e:
        logger.error(f"Error sending failure notification: {e}")
        return False


def run_dlt_script(
    script_path: str,
    target_table: str,
    working_dir: str = '/home/dlt',
    fail_on_error: bool = True,
    timeout: Optional[int] = 600,  # 10 minutes default
    extra_env: Optional[Dict[str, str]] = None,
    extra_args: Optional[List[str]] = None,
    pipeline_name: Optional[str] = None,
    send_notification_on_failure: bool = True,
) -> Dict[str, Any]:
    """
    Execute a DLT script with real-time log streaming.

    Args:
        script_path: Full path to the DLT Python script
        target_table: Target table name (for logging)
        working_dir: Working directory for script execution
        fail_on_error: If True, raise exception on errors (default: True)
        timeout: Timeout in seconds (default: 600 = 10 minutes)
        extra_env: Additional environment variables to set
        extra_args: Additional command line arguments to pass to the script
        pipeline_name: Name of the pipeline (for email notifications)
        send_notification_on_failure: If True, send email on failure (default: True)

    Returns:
        Dict with status, output, and error information

    Raises:
        Exception: If script fails and fail_on_error is True
    """
    start_time = datetime.now()

    # Build command with optional extra arguments
    cmd = [sys.executable, '-u', script_path]  # -u for unbuffered output
    if extra_args:
        cmd.extend(extra_args)

    # Use print for INFO level logs (Mage displays these normally)
    print(f"Starting DLT Script: {script_path}")
    print(f"Target Table: {target_table}")
    if extra_args:
        print(f"Arguments: {' '.join(extra_args)}")
    print(f"Timeout: {timeout} seconds")
    print("=" * 70)
    sys.stdout.flush()

    # Prepare environment
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'  # Force unbuffered output
    if extra_env:
        env.update(extra_env)

    # Track errors and output
    errors = []
    warnings = []
    output_lines = 0
    in_traceback = False

    # Execute script with real-time output streaming
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr into stdout
            text=True,
            cwd=working_dir,
            env=env,
            bufsize=1,  # Line buffered
        )

        # Read output in real-time
        deadline = time.time() + timeout if timeout else None

        while True:
            # Check timeout
            if deadline and time.time() > deadline:
                process.kill()
                process.wait()
                raise subprocess.TimeoutExpired(cmd, timeout)

            # Read line (with small timeout to check process status)
            try:
                line = process.stdout.readline()
            except Exception:
                break

            if line:
                line_stripped = line.rstrip('\n\r')
                output_lines += 1

                # Check for traceback
                if 'Traceback (most recent call last):' in line:
                    in_traceback = True
                    errors.append(line_stripped)
                    logger.error(f"[ERROR] {line_stripped}")
                    continue

                if in_traceback:
                    errors.append(line_stripped)
                    logger.error(f"[ERROR] {line_stripped}")
                    # End of traceback detection
                    if line_stripped and not line_stripped.startswith(' ') and not line_stripped.startswith('File'):
                        in_traceback = False
                    continue

                # Check for error indicators (case-insensitive, with exclusions)
                is_error = contains_indicator(line, ERROR_INDICATORS, ERROR_EXCLUSIONS)
                if is_error:
                    errors.append(line_stripped)
                    logger.error(f"[ERROR] {line_stripped}")
                else:
                    # Check for warnings (case-insensitive)
                    is_warning = contains_indicator(line, WARNING_INDICATORS)
                    if is_warning:
                        warnings.append(line_stripped)
                        logger.warning(f"[WARNING] {line_stripped}")
                    else:
                        # Normal output - print immediately
                        print(f"{line_stripped}")
                        sys.stdout.flush()

            elif process.poll() is not None:
                # Process finished
                break

        # Get return code
        return_code = process.returncode

    except subprocess.TimeoutExpired:
        logger.error(f"DLT script timed out after {timeout} seconds: {script_path}")
        raise Exception(f"DLT script timed out after {timeout} seconds: {script_path}")
    except Exception as e:
        logger.error(f"Failed to execute DLT script: {script_path} - {str(e)}")
        raise Exception(f"Failed to execute DLT script: {script_path}\nError: {str(e)}")

    # Calculate duration
    end_time = datetime.now()
    duration_seconds = (end_time - start_time).total_seconds()

    # Determine success/failure
    has_errors = len(errors) > 0 or return_code != 0

    # Save execution log for dashboard
    log_path = save_execution_log(
        script_path=script_path,
        target_table=target_table,
        status="failed" if has_errors else "success",
        return_code=return_code,
        errors=errors,
        warnings=warnings,
        output_lines=output_lines,
        duration_seconds=duration_seconds
    )

    # Build result
    output = {
        "status": "failed" if has_errors else "success",
        "target_table": target_table,
        "script_path": script_path,
        "return_code": return_code,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "output_lines": output_lines,
        "duration_seconds": round(duration_seconds, 2),
        "log_path": log_path,
    }

    # Print summary
    print("\n" + "=" * 70)
    if has_errors:
        # Use logger.error for failure summary
        logger.error(f"DLT SCRIPT FAILED: {script_path}")
        logger.error(f"  Return Code: {return_code}")
        logger.error(f"  Errors Found: {len(errors)}")
        if errors:
            logger.error("  Error Summary:")
            for err in errors[:10]:  # Show first 10 errors
                logger.error(f"    - {err[:200]}")  # Truncate long lines
    else:
        print(f"DLT SCRIPT COMPLETED SUCCESSFULLY")
        print(f"  Target: {target_table}")
        print(f"  Duration: {duration_seconds:.1f}s")
        print(f"  Output Lines: {output_lines}")
    print("=" * 70)
    sys.stdout.flush()

    # Handle failure
    if has_errors:
        # Send email notification on failure
        if send_notification_on_failure and pipeline_name:
            send_failure_notification(
                script_path=script_path,
                target_table=target_table,
                pipeline_name=pipeline_name,
                errors=errors,
                return_code=return_code,
                duration_seconds=duration_seconds,
                extra_args=extra_args,
            )

        if fail_on_error:
            error_summary = '\n'.join(errors[:5])
            raise Exception(
                f"DLT script failed: {script_path}\n"
                f"Return code: {return_code}\n"
                f"Errors:\n{error_summary}"
            )

    return output


def get_script_path(entity: str, mode: str = 'daily') -> str:
    """
    Get the DLT script path for a given entity.

    Args:
        entity: Entity name (e.g., 'projects', 'issues', 'users')
        mode: 'daily' or 'initial'

    Returns:
        Full path to the DLT script
    """
    return f'/home/dlt/jira/jira_{entity}.py'


def get_execution_logs(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get recent DLT execution logs for dashboard.

    Args:
        limit: Maximum number of logs to return

    Returns:
        List of log entries sorted by timestamp (newest first)
    """
    logs = []

    if not os.path.exists(DLT_LOGS_DIR):
        return logs

    try:
        for filename in os.listdir(DLT_LOGS_DIR):
            if filename.endswith('.json'):
                filepath = os.path.join(DLT_LOGS_DIR, filename)
                try:
                    with open(filepath, 'r') as f:
                        log_entry = json.load(f)
                        logs.append(log_entry)
                except Exception:
                    continue

        # Sort by timestamp descending
        logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

        return logs[:limit]
    except Exception:
        return []
