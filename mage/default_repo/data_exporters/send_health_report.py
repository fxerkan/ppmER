"""
Send Pipeline Health Report Email

This block sends a daily health report email with the status of all active pipelines.
"""

import sys
sys.path.insert(0, '/home/src/default_repo')

from datetime import datetime

if 'data_exporter' not in globals():
    from mage_ai.data_preparation.decorators import data_exporter


@data_exporter
def send_health_report(health_data, *args, **kwargs):
    """
    Send pipeline health report email.

    Args:
        health_data: Health check results from upstream block
    """
    from utils.pipeline_health_checker import format_health_report_html, format_health_report_text
    from utils.email_notifier import send_email, get_pipeline_recipients, load_pipeline_metadata

    # Get pipeline info
    pipeline_uuid = kwargs.get('pipeline_uuid', 'pipeline_health_monitor')

    print("=" * 70)
    print("SENDING PIPELINE HEALTH REPORT")
    print("=" * 70)

    # Load recipients from pipeline metadata
    recipients = get_pipeline_recipients(pipeline_uuid, notification_type='email_on_success')

    if not recipients['to']:
        print("⚠ No recipients configured for health report")
        print("Add email addresses to pipeline metadata.yaml under:")
        print("  custom_notifications:")
        print("    email_on_success:")
        print("      to:")
        print("        - your-email@example.com")
        return {'notification_sent': False, 'reason': 'no_recipients'}

    # Format email content
    subject = f"📊 Daily Pipeline Health Report - {datetime.now().strftime('%Y-%m-%d')}"
    html_body = format_health_report_html(health_data)
    text_body = format_health_report_text(health_data)

    # Send email
    print(f"\nSending health report to: {', '.join(recipients['to'])}")

    success = send_email(
        subject=subject,
        body_html=html_body,
        body_text=text_body,
        to_emails=recipients['to'],
        cc_emails=recipients['cc'],
        bcc_emails=recipients['bcc'],
    )

    if success:
        print("✓ Health report email sent successfully!")
    else:
        print("✗ Failed to send health report email")

    print("=" * 70)

    return {
        'notification_sent': success,
        'recipients': recipients['to'],
        'total_active_pipelines': health_data['total_active_pipelines'],
        'check_time': health_data['check_time'].isoformat(),
    }
