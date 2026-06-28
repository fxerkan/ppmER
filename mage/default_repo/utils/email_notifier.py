"""
Email Notification Utility for Mage.ai Pipelines

This module provides email notification functionality for pipeline failures,
successes, and stuck pipeline detection.

SMTP Configuration (via environment variables):
- SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_MAIL_FROM
- SMTP_SSL, SMTP_STARTTLS
- MAGE_BASE_URL (optional, defaults to http://localhost:6789)

Recipient Configuration (via pipeline metadata.yaml):
- custom_notifications.email_on_failure.to / cc / bcc
- custom_notifications.email_on_success.to / cc / bcc

NOTE: We use 'custom_notifications' instead of 'notification_config' to avoid
conflicts with Mage's built-in notification system.
"""

import os
import smtplib
import ssl
import yaml
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional, List, Dict, Any
import traceback
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Path to pipelines directory
PIPELINES_DIR = '/home/src/default_repo/pipelines'

# Default Mage base URL for generating links
DEFAULT_MAGE_BASE_URL = 'http://localhost:6789'


def get_mage_base_url() -> str:
    """Get Mage AI base URL from environment or use default."""
    return os.getenv('DEFAULT_MAGE_BASE_URL', DEFAULT_MAGE_BASE_URL)


def build_pipeline_urls(pipeline_uuid: str, run_id: Optional[str] = None, trigger_id: Optional[str] = None) -> Dict[str, str]:
    """
    Build URLs for pipeline runs, logs, and triggers.

    Args:
        pipeline_uuid: The pipeline UUID
        run_id: Optional run ID for run-specific URLs (should be numeric)
        trigger_id: Optional trigger ID for trigger URL

    Returns:
        Dictionary with pipeline_url, run_url, logs_url, trigger_url
    """
    base_url = get_mage_base_url()

    urls = {
        'pipeline_url': f"{base_url}/pipelines/{pipeline_uuid}",
        'run_url': None,
        'logs_url': None,
        'trigger_url': None,
    }

    if run_id:
        # Extract numeric run_id if it's in execution_partition format (e.g., "2/20251220T090000")
        # We only want the numeric part (e.g., "2" or "186")
        run_id_str = str(run_id)
        if '/' in run_id_str:
            # Extract the first part before the slash
            numeric_run_id = run_id_str.split('/')[0]
        else:
            numeric_run_id = run_id_str

        urls['run_url'] = f"{base_url}/pipelines/{pipeline_uuid}/runs/{numeric_run_id}"
        urls['logs_url'] = f"{base_url}/pipelines/{pipeline_uuid}/logs?pipeline_run_id[]={numeric_run_id}"

    if trigger_id:
        urls['trigger_url'] = f"{base_url}/pipelines/{pipeline_uuid}/triggers/{trigger_id}"

    return urls


def get_smtp_config() -> Dict[str, Any]:
    """Get SMTP configuration from environment variables."""
    return {
        'host': os.getenv('SMTP_HOST', 'smtp.gmail.com'),
        'port': int(os.getenv('SMTP_PORT', '465')),
        'user': os.getenv('SMTP_USER', ''),
        'password': os.getenv('SMTP_PASSWORD', ''),
        'mail_from': os.getenv('SMTP_MAIL_FROM', ''),
        'ssl': os.getenv('SMTP_SSL', 'True').lower() in ('true', '1', 'yes'),
        'starttls': os.getenv('SMTP_STARTTLS', 'False').lower() in ('true', '1', 'yes'),
    }


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
        logger.warning(f"Pipeline metadata not found: {metadata_path}")
        return {}

    try:
        with open(metadata_path, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Error loading pipeline metadata: {e}")
        return {}


def get_pipeline_recipients(
    pipeline_name: str,
    custom_notifications: Optional[Dict[str, Any]] = None,
    notification_type: str = 'email_on_failure',
) -> Dict[str, List[str]]:
    """
    Get email recipients for a specific pipeline from pipeline configuration.

    Recipients are read from the pipeline's metadata.yaml file:
    custom_notifications:
      email_on_failure:
        to:
          - user1@example.com
        cc: []
        bcc: []
      email_on_success:
        to:
          - user2@example.com
        cc: []
        bcc: []

    NOTE: We use 'custom_notifications' instead of 'notification_config' to avoid
    conflicts with Mage's built-in notification system.

    Args:
        pipeline_name: Name of the pipeline
        custom_notifications: Optional custom notifications dict (if already loaded)
        notification_type: Type of notification ('email_on_failure' or 'email_on_success')

    Returns:
        Dictionary with 'to', 'cc', 'bcc' lists of email addresses
    """
    # If custom_notifications is provided directly, use it
    if custom_notifications:
        email_config = custom_notifications.get(notification_type, {})
    else:
        # Load from pipeline metadata
        metadata = load_pipeline_metadata(pipeline_name)
        email_config = metadata.get('custom_notifications', {}).get(notification_type, {})

    def parse_emails(value: Any) -> List[str]:
        """Parse email addresses from various formats."""
        if not value:
            return []
        if isinstance(value, str):
            # Comma-separated string
            return [email.strip() for email in value.split(',') if email.strip()]
        if isinstance(value, list):
            # List of emails
            return [email.strip() for email in value if email and email.strip()]
        return []

    return {
        'to': parse_emails(email_config.get('to')),
        'cc': parse_emails(email_config.get('cc')),
        'bcc': parse_emails(email_config.get('bcc')),
    }


def send_email(
    subject: str,
    body_html: str,
    body_text: str,
    to_emails: List[str],
    cc_emails: Optional[List[str]] = None,
    bcc_emails: Optional[List[str]] = None,
) -> bool:
    """
    Send an email using SMTP configuration from environment variables.

    Args:
        subject: Email subject
        body_html: HTML body content
        body_text: Plain text body content
        to_emails: List of recipient email addresses
        cc_emails: List of CC email addresses
        bcc_emails: List of BCC email addresses

    Returns:
        True if email sent successfully, False otherwise
    """
    config = get_smtp_config()

    if not config['user'] or not config['password']:
        logger.error("SMTP credentials not configured. Set SMTP_USER and SMTP_PASSWORD.")
        return False

    if not to_emails:
        logger.error("No recipient emails provided.")
        return False

    cc_emails = cc_emails or []
    bcc_emails = bcc_emails or []

    # Create message
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = config['mail_from'] or config['user']
    msg['To'] = ', '.join(to_emails)

    if cc_emails:
        msg['Cc'] = ', '.join(cc_emails)

    # Attach plain text and HTML parts
    part1 = MIMEText(body_text, 'plain')
    part2 = MIMEText(body_html, 'html')
    msg.attach(part1)
    msg.attach(part2)

    # All recipients for SMTP sendmail
    all_recipients = to_emails + cc_emails + bcc_emails

    try:
        if config['ssl']:
            # SSL connection (port 465)
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(config['host'], config['port'], context=context) as server:
                server.login(config['user'], config['password'])
                server.sendmail(config['mail_from'] or config['user'], all_recipients, msg.as_string())
        else:
            # STARTTLS connection (port 587)
            with smtplib.SMTP(config['host'], config['port']) as server:
                server.ehlo()  # ⭐ REQUIRED: Say hello first

                if config['starttls']:
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                    server.ehlo()  # ⭐ REQUIRED: Say hello again after STARTTLS

                server.login(config['user'], config['password'])
                server.sendmail(config['mail_from'] or config['user'], all_recipients, msg.as_string())

        logger.info(f"Email sent successfully to {', '.join(to_emails)}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        logger.error(traceback.format_exc())
        return False


def send_pipeline_failure_notification(
    pipeline_name: str,
    pipeline_uuid: str,
    block_name: Optional[str] = None,
    error_message: Optional[str] = None,
    error_traceback: Optional[str] = None,
    execution_date: Optional[datetime] = None,
    run_id: Optional[str] = None,
    trigger_id: Optional[str] = None,
    trigger_name: Optional[str] = None,
    trigger_params: Optional[Dict[str, Any]] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    execution_duration_seconds: Optional[float] = None,
    blocks_executed: Optional[List[str]] = None,
    execution_logs: Optional[str] = None,
    additional_context: Optional[Dict[str, Any]] = None,
    custom_notifications: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Send a pipeline failure notification email.

    Args:
        pipeline_name: Name of the failed pipeline
        pipeline_uuid: UUID of the pipeline run
        block_name: Name of the failed block (if applicable)
        error_message: Error message
        error_traceback: Full error traceback
        execution_date: When the pipeline was executed
        run_id: Pipeline run ID
        trigger_id: Trigger ID that initiated the run
        trigger_name: Name of the trigger
        trigger_params: Trigger runtime parameters
        start_time: Pipeline start time
        end_time: Pipeline end time
        execution_duration_seconds: Total execution time in seconds
        blocks_executed: List of all blocks that were executed
        execution_logs: Recent execution logs
        additional_context: Any additional context to include
        custom_notifications: Optional custom notifications config (from pipeline metadata)

    Returns:
        True if email sent successfully, False otherwise
    """
    recipients = get_pipeline_recipients(pipeline_name, custom_notifications, 'email_on_failure')

    if not recipients['to']:
        logger.warning(f"No recipients configured for pipeline '{pipeline_name}'. "
                      f"Add custom_notifications.email_on_failure.to in pipeline metadata.yaml")
        return False

    execution_date = execution_date or datetime.now()

    # Build URLs for the email
    urls = build_pipeline_urls(pipeline_uuid, run_id, trigger_id)

    subject = f"Pipeline FAILED: {pipeline_name}"
    if block_name:
        subject += f" (Block: {block_name})"

    # Format execution duration
    duration_str = ""
    if execution_duration_seconds is not None:
        minutes = int(execution_duration_seconds // 60)
        seconds = int(execution_duration_seconds % 60)
        if minutes > 0:
            duration_str = f"{minutes}m {seconds}s"
        else:
            duration_str = f"{seconds}s"

    # Build URL links section for HTML
    url_links_html = ""
    if urls['run_url'] or urls['logs_url'] or urls['trigger_url']:
        url_links_html = '<div class="links-box"><strong>Quick Links:</strong><ul>'
        if urls['run_url']:
            url_links_html += f'<li><a href="{urls["run_url"]}">View Pipeline Run</a></li>'
        if urls['logs_url']:
            url_links_html += f'<li><a href="{urls["logs_url"]}">View Execution Logs</a></li>'
        if urls['trigger_url']:
            url_links_html += f'<li><a href="{urls["trigger_url"]}">View Trigger Configuration</a></li>'
        url_links_html += f'<li><a href="{urls["pipeline_url"]}">View Pipeline</a></li>'
        url_links_html += '</ul></div>'

    # Build URL links section for plain text
    url_links_text = ""
    if urls['run_url'] or urls['logs_url'] or urls['trigger_url']:
        url_links_text = "\nQuick Links:\n"
        if urls['run_url']:
            url_links_text += f"- Pipeline Run: {urls['run_url']}\n"
        if urls['logs_url']:
            url_links_text += f"- Execution Logs: {urls['logs_url']}\n"
        if urls['trigger_url']:
            url_links_text += f"- Trigger Config: {urls['trigger_url']}\n"
        url_links_text += f"- Pipeline: {urls['pipeline_url']}\n"

    # Build trigger parameters section
    trigger_params_html = ""
    trigger_params_text = ""
    if trigger_params:
        trigger_params_html = '<div class="params-box"><strong>Trigger Parameters:</strong><ul>'
        trigger_params_text = "\nTrigger Parameters:\n"
        for key, value in trigger_params.items():
            trigger_params_html += f'<li><strong>{key}:</strong> {value}</li>'
            trigger_params_text += f"- {key}: {value}\n"
        trigger_params_html += '</ul></div>'

    # Build HTML body
    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
            .header {{ background-color: #dc3545; color: white; padding: 20px; border-radius: 5px 5px 0 0; }}
            .content {{ background-color: #f8f9fa; padding: 20px; border: 1px solid #dee2e6; }}
            .info-table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
            .info-table td {{ padding: 8px; border-bottom: 1px solid #dee2e6; }}
            .info-table td:first-child {{ font-weight: bold; width: 150px; }}
            .error-box {{ background-color: #fff3cd; border: 1px solid #ffc107; border-radius: 5px; padding: 15px; margin: 15px 0; }}
            .links-box {{ background-color: #e3f2fd; border: 1px solid #2196F3; border-radius: 5px; padding: 15px; margin: 15px 0; }}
            .links-box ul {{ margin: 10px 0 0 20px; padding: 0; }}
            .links-box li {{ margin: 5px 0; }}
            .links-box a {{ color: #1976D2; text-decoration: none; }}
            .links-box a:hover {{ text-decoration: underline; }}
            .params-box {{ background-color: #fff3e0; border: 1px solid #ff9800; border-radius: 5px; padding: 15px; margin: 15px 0; }}
            .params-box ul {{ margin: 10px 0 0 20px; padding: 0; }}
            .traceback {{ background-color: #282c34; color: #abb2bf; padding: 15px; border-radius: 5px;
                         font-family: 'Courier New', monospace; font-size: 12px; overflow-x: auto; white-space: pre-wrap; }}
            .logs-box {{ background-color: #263238; color: #B0BEC5; padding: 15px; border-radius: 5px;
                        font-family: 'Courier New', monospace; font-size: 11px; overflow-x: auto; white-space: pre-wrap; max-height: 400px; overflow-y: auto; }}
            .footer {{ text-align: center; padding: 15px; color: #6c757d; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>Pipeline Failure Alert</h2>
            </div>
            <div class="content">
                <table class="info-table">
                    <tr><td>Pipeline Name:</td><td><strong>{pipeline_name}</strong></td></tr>
                    <tr><td>Pipeline UUID:</td><td>{pipeline_uuid}</td></tr>
                    {"<tr><td>Trigger Name:</td><td><strong>" + trigger_name + "</strong></td></tr>" if trigger_name else ""}
                    {"<tr><td>Trigger ID:</td><td>" + str(trigger_id) + "</td></tr>" if trigger_id else ""}
                    {"<tr><td>Failed Block:</td><td><strong style='color: #dc3545;'>" + block_name + "</strong></td></tr>" if block_name else ""}
                    {"<tr><td>Run ID:</td><td>" + str(run_id) + "</td></tr>" if run_id else ""}
                    {"<tr><td>Start Time:</td><td>" + start_time.strftime('%Y-%m-%d %H:%M:%S UTC') + "</td></tr>" if start_time else ""}
                    {"<tr><td>End Time:</td><td>" + end_time.strftime('%Y-%m-%d %H:%M:%S UTC') + "</td></tr>" if end_time else ""}
                    {"<tr><td>Duration:</td><td><strong>" + duration_str + "</strong></td></tr>" if duration_str else ""}
                    <tr><td>Status:</td><td><span style="color: #dc3545; font-weight: bold;">FAILED</span></td></tr>
                </table>

                {url_links_html}

                {trigger_params_html}

                {f'<div class="error-box"><strong>Error Message:</strong><br>{error_message}</div>' if error_message else ''}

                {f'<h4>Error Traceback:</h4><div class="traceback">{error_traceback}</div>' if error_traceback else ''}

                {f'<h4>Execution Logs (Recent):</h4><div class="logs-box">{execution_logs}</div>' if execution_logs else ''}

                {f'<h4>Additional Context:</h4><pre>{additional_context}</pre>' if additional_context else ''}
            </div>
            <div class="footer">
                <p>This is an automated notification from Mage.ai Pipeline Monitoring</p>
                <p>PPM Data Stack - {datetime.now().strftime('%Y')}</p>
            </div>
        </div>
    </body>
    </html>
    """

    # Build plain text body
    text_body = f"""
PIPELINE FAILURE ALERT
======================

Pipeline Name: {pipeline_name}
Pipeline UUID: {pipeline_uuid}
{"Trigger Name: " + trigger_name if trigger_name else ""}
{"Trigger ID: " + str(trigger_id) if trigger_id else ""}
{"Failed Block: " + block_name if block_name else ""}
{"Run ID: " + str(run_id) if run_id else ""}
{"Start Time: " + start_time.strftime('%Y-%m-%d %H:%M:%S UTC') if start_time else ""}
{"End Time: " + end_time.strftime('%Y-%m-%d %H:%M:%S UTC') if end_time else ""}
{"Duration: " + duration_str if duration_str else ""}
Status: FAILED
{url_links_text}
{trigger_params_text}
{"Error Message: " + error_message if error_message else ""}

{"Error Traceback:" + chr(10) + error_traceback if error_traceback else ""}

{"Execution Logs:" + chr(10) + execution_logs if execution_logs else ""}

{"Additional Context:" + chr(10) + str(additional_context) if additional_context else ""}

---
This is an automated notification from Mage.ai Pipeline Monitoring
PPM Data Stack - {datetime.now().strftime('%Y')}
"""

    return send_email(
        subject=subject,
        body_html=html_body,
        body_text=text_body,
        to_emails=recipients['to'],
        cc_emails=recipients['cc'],
        bcc_emails=recipients['bcc'],
    )


def send_pipeline_stuck_notification(
    pipeline_name: str,
    pipeline_uuid: str,
    start_time: datetime,
    current_duration_minutes: float,
    expected_duration_minutes: float,
    threshold_multiplier: float = 2.0,
    run_id: Optional[str] = None,
    current_block: Optional[str] = None,
    custom_notifications: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Send a notification when a pipeline appears to be stuck.

    Args:
        pipeline_name: Name of the stuck pipeline
        pipeline_uuid: UUID of the pipeline run
        start_time: When the pipeline started
        current_duration_minutes: How long the pipeline has been running (minutes)
        expected_duration_minutes: Normal expected duration (minutes)
        threshold_multiplier: Multiplier for stuck detection (default 2x)
        run_id: Pipeline run ID
        current_block: Currently executing block name
        custom_notifications: Optional custom notifications config (from pipeline metadata)

    Returns:
        True if email sent successfully, False otherwise
    """
    recipients = get_pipeline_recipients(pipeline_name, custom_notifications)

    if not recipients['to']:
        logger.warning(f"No recipients configured for pipeline '{pipeline_name}'.")
        return False

    subject = f"Pipeline STUCK: {pipeline_name} (Running {current_duration_minutes:.0f}+ minutes)"

    # Build HTML body
    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
            .header {{ background-color: #ffc107; color: #212529; padding: 20px; border-radius: 5px 5px 0 0; }}
            .content {{ background-color: #f8f9fa; padding: 20px; border: 1px solid #dee2e6; }}
            .info-table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
            .info-table td {{ padding: 8px; border-bottom: 1px solid #dee2e6; }}
            .info-table td:first-child {{ font-weight: bold; width: 180px; }}
            .warning-box {{ background-color: #fff3cd; border: 1px solid #ffc107; border-radius: 5px; padding: 15px; margin: 15px 0; }}
            .footer {{ text-align: center; padding: 15px; color: #6c757d; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>Pipeline Stuck Alert</h2>
            </div>
            <div class="content">
                <div class="warning-box">
                    <strong>Warning:</strong> Pipeline has been running for <strong>{current_duration_minutes:.0f} minutes</strong>,
                    which exceeds the expected duration of {expected_duration_minutes:.0f} minutes
                    by more than {threshold_multiplier}x threshold.
                </div>

                <table class="info-table">
                    <tr><td>Pipeline Name:</td><td><strong>{pipeline_name}</strong></td></tr>
                    <tr><td>Pipeline UUID:</td><td>{pipeline_uuid}</td></tr>
                    {"<tr><td>Run ID:</td><td>" + str(run_id) + "</td></tr>" if run_id else ""}
                    <tr><td>Start Time:</td><td>{start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}</td></tr>
                    <tr><td>Current Duration:</td><td><strong style="color: #dc3545;">{current_duration_minutes:.0f} minutes</strong></td></tr>
                    <tr><td>Expected Duration:</td><td>{expected_duration_minutes:.0f} minutes</td></tr>
                    <tr><td>Threshold:</td><td>{threshold_multiplier}x ({expected_duration_minutes * threshold_multiplier:.0f} minutes)</td></tr>
                    {"<tr><td>Current Block:</td><td>" + current_block + "</td></tr>" if current_block else ""}
                    <tr><td>Status:</td><td><span style="color: #ffc107; font-weight: bold;">POTENTIALLY STUCK</span></td></tr>
                </table>

                <h4>Recommended Actions:</h4>
                <ul>
                    <li>Check the Mage.ai UI for the pipeline status</li>
                    <li>Review the logs for any errors or long-running operations</li>
                    <li>Consider canceling and restarting the pipeline if stuck</li>
                    <li>Check for database locks or external service issues</li>
                </ul>
            </div>
            <div class="footer">
                <p>This is an automated notification from Mage.ai Pipeline Monitoring</p>
                <p>PPM Data Stack - {datetime.now().strftime('%Y')}</p>
            </div>
        </div>
    </body>
    </html>
    """

    # Build plain text body
    text_body = f"""
PIPELINE STUCK ALERT
====================

WARNING: Pipeline has been running for {current_duration_minutes:.0f} minutes,
which exceeds the expected duration of {expected_duration_minutes:.0f} minutes
by more than {threshold_multiplier}x threshold.

Pipeline Name: {pipeline_name}
Pipeline UUID: {pipeline_uuid}
{"Run ID: " + str(run_id) if run_id else ""}
Start Time: {start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}
Current Duration: {current_duration_minutes:.0f} minutes
Expected Duration: {expected_duration_minutes:.0f} minutes
Threshold: {threshold_multiplier}x ({expected_duration_minutes * threshold_multiplier:.0f} minutes)
{"Current Block: " + current_block if current_block else ""}
Status: POTENTIALLY STUCK

Recommended Actions:
- Check the Mage.ai UI for the pipeline status
- Review the logs for any errors or long-running operations
- Consider canceling and restarting the pipeline if stuck
- Check for database locks or external service issues

---
This is an automated notification from Mage.ai Pipeline Monitoring
PPM Data Stack - {datetime.now().strftime('%Y')}
"""

    return send_email(
        subject=subject,
        body_html=html_body,
        body_text=text_body,
        to_emails=recipients['to'],
        cc_emails=recipients['cc'],
        bcc_emails=recipients['bcc'],
    )


def send_pipeline_success_notification(
    pipeline_name: str,
    pipeline_uuid: str,
    execution_date: Optional[datetime] = None,
    run_id: Optional[str] = None,
    trigger_id: Optional[str] = None,
    trigger_name: Optional[str] = None,
    trigger_params: Optional[Dict[str, Any]] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    execution_duration_seconds: Optional[float] = None,
    blocks_executed: Optional[List[str]] = None,
    execution_logs: Optional[str] = None,
    additional_context: Optional[Dict[str, Any]] = None,
    custom_notifications: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Send a pipeline success notification email.

    Args:
        pipeline_name: Name of the successful pipeline
        pipeline_uuid: UUID of the pipeline run
        execution_date: When the pipeline was executed
        run_id: Pipeline run ID
        trigger_id: Trigger ID that initiated the run
        trigger_name: Name of the trigger
        trigger_params: Trigger runtime parameters
        start_time: Pipeline start time
        end_time: Pipeline end time
        execution_duration_seconds: Total execution time in seconds
        blocks_executed: List of blocks that were executed
        execution_logs: Recent execution logs (last N lines)
        additional_context: Any additional context to include
        custom_notifications: Optional custom notifications config (from pipeline metadata)

    Returns:
        True if email sent successfully, False otherwise
    """
    recipients = get_pipeline_recipients(pipeline_name, custom_notifications, 'email_on_success')

    if not recipients['to']:
        logger.info(f"No success notification recipients configured for pipeline '{pipeline_name}'. "
                   f"Add custom_notifications.email_on_success.to in pipeline metadata.yaml")
        return False

    execution_date = execution_date or datetime.now()

    # Build URLs for the email
    urls = build_pipeline_urls(pipeline_uuid, run_id, trigger_id)

    subject = f"Pipeline SUCCESS: {pipeline_name}"

    # Format execution duration
    duration_str = ""
    if execution_duration_seconds:
        minutes = int(execution_duration_seconds // 60)
        seconds = int(execution_duration_seconds % 60)
        if minutes > 0:
            duration_str = f"{minutes}m {seconds}s"
        else:
            duration_str = f"{seconds}s"

    # Build URL links section for HTML
    url_links_html = ""
    if urls['run_url'] or urls['logs_url'] or urls['trigger_url']:
        url_links_html = '<div class="links-box"><strong>Quick Links:</strong><ul>'
        if urls['run_url']:
            url_links_html += f'<li><a href="{urls["run_url"]}">View Pipeline Run</a></li>'
        if urls['logs_url']:
            url_links_html += f'<li><a href="{urls["logs_url"]}">View Execution Logs</a></li>'
        if urls['trigger_url']:
            url_links_html += f'<li><a href="{urls["trigger_url"]}">View Trigger Configuration</a></li>'
        url_links_html += f'<li><a href="{urls["pipeline_url"]}">View Pipeline</a></li>'
        url_links_html += '</ul></div>'

    # Build URL links section for plain text
    url_links_text = ""
    if urls['run_url'] or urls['logs_url'] or urls['trigger_url']:
        url_links_text = "\nQuick Links:\n"
        if urls['run_url']:
            url_links_text += f"- Pipeline Run: {urls['run_url']}\n"
        if urls['logs_url']:
            url_links_text += f"- Execution Logs: {urls['logs_url']}\n"
        if urls['trigger_url']:
            url_links_text += f"- Trigger Config: {urls['trigger_url']}\n"
        url_links_text += f"- Pipeline: {urls['pipeline_url']}\n"

    # Build trigger parameters section
    trigger_params_html = ""
    if trigger_params:
        trigger_params_html = '<div class="params-box"><strong>Trigger Parameters:</strong><ul>'
        for key, value in trigger_params.items():
            trigger_params_html += f'<li><strong>{key}:</strong> {value}</li>'
        trigger_params_html += '</ul></div>'

    # Build HTML body
    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
            .header {{ background-color: #28a745; color: white; padding: 20px; border-radius: 5px 5px 0 0; }}
            .content {{ background-color: #f8f9fa; padding: 20px; border: 1px solid #dee2e6; }}
            .info-table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
            .info-table td {{ padding: 8px; border-bottom: 1px solid #dee2e6; }}
            .info-table td:first-child {{ font-weight: bold; width: 150px; }}
            .success-box {{ background-color: #d4edda; border: 1px solid #28a745; border-radius: 5px; padding: 15px; margin: 15px 0; }}
            .links-box {{ background-color: #e3f2fd; border: 1px solid #2196F3; border-radius: 5px; padding: 15px; margin: 15px 0; }}
            .links-box ul {{ margin: 10px 0 0 20px; padding: 0; }}
            .links-box li {{ margin: 5px 0; }}
            .links-box a {{ color: #1976D2; text-decoration: none; }}
            .links-box a:hover {{ text-decoration: underline; }}
            .blocks-box {{ background-color: #fff3e0; border: 1px solid #ff9800; border-radius: 5px; padding: 15px; margin: 15px 0; }}
            .blocks-box ul {{ margin: 10px 0 0 20px; padding: 0; }}
            .logs-box {{ background-color: #263238; color: #B0BEC5; padding: 15px; border-radius: 5px;
                        font-family: 'Courier New', monospace; font-size: 11px; overflow-x: auto; white-space: pre-wrap; max-height: 300px; overflow-y: auto; }}
            .footer {{ text-align: center; padding: 15px; color: #6c757d; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>Pipeline Success Notification</h2>
            </div>
            <div class="content">
                <div class="success-box">
                    <strong>Pipeline completed successfully!</strong>
                </div>

                <table class="info-table">
                    <tr><td>Pipeline Name:</td><td><strong>{pipeline_name}</strong></td></tr>
                    <tr><td>Pipeline UUID:</td><td>{pipeline_uuid}</td></tr>
                    {"<tr><td>Trigger Name:</td><td><strong>" + trigger_name + "</strong></td></tr>" if trigger_name else ""}
                    {"<tr><td>Trigger ID:</td><td>" + str(trigger_id) + "</td></tr>" if trigger_id else ""}
                    {"<tr><td>Run ID:</td><td>" + str(run_id) + "</td></tr>" if run_id else ""}
                    {"<tr><td>Start Time:</td><td>" + start_time.strftime('%Y-%m-%d %H:%M:%S UTC') + "</td></tr>" if start_time else ""}
                    {"<tr><td>End Time:</td><td>" + end_time.strftime('%Y-%m-%d %H:%M:%S UTC') + "</td></tr>" if end_time else ""}
                    {"<tr><td>Duration:</td><td><strong>" + duration_str + "</strong></td></tr>" if duration_str else ""}
                    <tr><td>Status:</td><td><span style="color: #28a745; font-weight: bold;">SUCCESS</span></td></tr>
                </table>

                {url_links_html}

                {trigger_params_html}

                {f'<h4>Execution Logs (Recent):</h4><div class="logs-box">{execution_logs}</div>' if execution_logs else ''}

                {f'<h4>Additional Context:</h4><pre>{additional_context}</pre>' if additional_context else ''}
            </div>
            <div class="footer">
                <p>This is an automated notification from Mage.ai Pipeline Monitoring</p>
                <p>PPM Data Stack - {datetime.now().strftime('%Y')}</p>
            </div>
        </div>
    </body>
    </html>
    """

    # Build plain text body
    trigger_params_text = ""
    if trigger_params:
        trigger_params_text = "\nTrigger Parameters:\n"
        for key, value in trigger_params.items():
            trigger_params_text += f"- {key}: {value}\n"

    text_body = f"""
PIPELINE SUCCESS NOTIFICATION
=============================

Pipeline completed successfully!

Pipeline Name: {pipeline_name}
Pipeline UUID: {pipeline_uuid}
{"Trigger Name: " + trigger_name if trigger_name else ""}
{"Trigger ID: " + str(trigger_id) if trigger_id else ""}
{"Run ID: " + str(run_id) if run_id else ""}
{"Start Time: " + start_time.strftime('%Y-%m-%d %H:%M:%S UTC') if start_time else ""}
{"End Time: " + end_time.strftime('%Y-%m-%d %H:%M:%S UTC') if end_time else ""}
{"Duration: " + duration_str if duration_str else ""}
Status: SUCCESS
{url_links_text}
{trigger_params_text}

{"Execution Logs:" + chr(10) + execution_logs if execution_logs else ""}

{"Additional Context:" + chr(10) + str(additional_context) if additional_context else ""}

---
This is an automated notification from Mage.ai Pipeline Monitoring
PPM Data Stack - {datetime.now().strftime('%Y')}
"""

    return send_email(
        subject=subject,
        body_html=html_body,
        body_text=text_body,
        to_emails=recipients['to'],
        cc_emails=recipients['cc'],
        bcc_emails=recipients['bcc'],
    )


def test_email_connection() -> bool:
    """
    Test SMTP connection.

    Returns:
        True if test successful, False otherwise
    """
    config = get_smtp_config()

    logger.info(f"Testing SMTP connection to {config['host']}:{config['port']}")
    logger.info(f"SSL: {config['ssl']}, STARTTLS: {config['starttls']}")

    try:
        if config['ssl']:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(config['host'], config['port'], context=context) as server:
                server.login(config['user'], config['password'])
                logger.info("SMTP SSL connection successful!")
        else:
            with smtplib.SMTP(config['host'], config['port']) as server:
                if config['starttls']:
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                server.login(config['user'], config['password'])
                logger.info("SMTP connection successful!")
        return True
    except Exception as e:
        logger.error(f"SMTP connection failed: {str(e)}")
        return False


if __name__ == '__main__':
    # Test the email connection
    test_email_connection()
