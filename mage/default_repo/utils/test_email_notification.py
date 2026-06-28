#!/usr/bin/env python3
"""
Test Script for Email Notifications

Run this script to verify email notification setup is working correctly.

Usage:
    python test_email_notification.py

Make sure to set the environment variables in .env file before running.
"""

import os
import sys
from datetime import datetime

# Load environment variables from .env file
def load_env():
    """Load environment variables from .env file."""
    env_file = '/Users/erkanciftci/repo_local/firmax-2025/ppm-data-stack/.env'
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")
        print(f"Loaded environment variables from {env_file}")
    else:
        print(f"Warning: .env file not found at {env_file}")


def test_email_connection():
    """Test SMTP connection."""
    from email_notifier import test_email_connection as _test
    print("\n" + "=" * 60)
    print("TEST 1: SMTP Connection Test")
    print("=" * 60)
    result = _test()
    print(f"Result: {'SUCCESS' if result else 'FAILED'}")
    return result


def test_send_failure_notification():
    """Test sending a pipeline failure notification."""
    from email_notifier import send_pipeline_failure_notification
    print("\n" + "=" * 60)
    print("TEST 2: Pipeline Failure Notification")
    print("=" * 60)

    result = send_pipeline_failure_notification(
        pipeline_name='master_daily_jira',
        pipeline_uuid='master_daily_jira_test',
        block_name='dlt_load_jira_issues',
        error_message='Test error: This is a test failure notification.',
        error_traceback='Traceback (most recent call last):\n  File "test.py", line 1\n    raise Exception("Test error")\nException: Test error',
        execution_date=datetime.now(),
        run_id='TEST_RUN_001',
        additional_context={
            'test_mode': True,
            'purpose': 'Verify email notifications are working',
        },
    )

    print(f"Result: {'SUCCESS' if result else 'FAILED'}")
    return result


def test_send_stuck_notification():
    """Test sending a stuck pipeline notification."""
    from email_notifier import send_pipeline_stuck_notification
    print("\n" + "=" * 60)
    print("TEST 3: Stuck Pipeline Notification")
    print("=" * 60)

    result = send_pipeline_stuck_notification(
        pipeline_name='master_daily_jira',
        pipeline_uuid='master_daily_jira_test',
        start_time=datetime.now(),
        current_duration_minutes=120,
        expected_duration_minutes=45,
        threshold_multiplier=2.0,
        run_id='TEST_RUN_002',
        current_block='dlt_load_jira_worklogs (running for 90+ mins)',
    )

    print(f"Result: {'SUCCESS' if result else 'FAILED'}")
    return result


def check_recipients():
    """Check recipient configuration."""
    from email_notifier import get_pipeline_recipients
    print("\n" + "=" * 60)
    print("RECIPIENT CONFIGURATION CHECK")
    print("=" * 60)

    pipelines = ['jira_issues', 'jira_worklogs', 'master_daily_jira', 'master_initial_jira', 'master_sharepoint', 'test_success_notification', 'test_email_notification']

    for pipeline in pipelines:
        recipients = get_pipeline_recipients(pipeline)
        print(f"\n{pipeline}:")
        print(f"  TO:  {recipients['to'] or '(not configured)'}")
        print(f"  CC:  {recipients['cc'] or '(not configured)'}")
        print(f"  BCC: {recipients['bcc'] or '(not configured)'}")


def main():
    print("=" * 60)
    print("EMAIL NOTIFICATION TEST SUITE")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Load environment variables
    load_env()

    # Check SMTP configuration
    print("\n" + "=" * 60)
    print("SMTP CONFIGURATION")
    print("=" * 60)
    print(f"SMTP_HOST: {os.getenv('SMTP_HOST', 'not set')}")
    print(f"SMTP_PORT: {os.getenv('SMTP_PORT', 'not set')}")
    print(f"SMTP_USER: {os.getenv('SMTP_USER', 'not set')}")
    print(f"SMTP_MAIL_FROM: {os.getenv('SMTP_MAIL_FROM', 'not set')}")
    print(f"SMTP_SSL: {os.getenv('SMTP_SSL', 'not set')}")
    print(f"SMTP_USE_TLS: {os.getenv('SMTP_USE_TLS', 'not set')}")
    print(f"SMTP_PASSWORD: {'***' if os.getenv('SMTP_PASSWORD') else 'not set'}")

    # Check recipients
    check_recipients()

    # Run tests
    tests_passed = 0
    tests_failed = 0

    if test_email_connection():
        tests_passed += 1
    else:
        tests_failed += 1

    if test_send_failure_notification():
        tests_passed += 1
    else:
        tests_failed += 1

    if test_send_stuck_notification():
        tests_passed += 1
    else:
        tests_failed += 1

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Tests Passed: {tests_passed}")
    print(f"Tests Failed: {tests_failed}")
    print(f"Total Tests: {tests_passed + tests_failed}")
    print("=" * 60)

    if tests_failed == 0:
        print("\n✓ All tests passed! Email notifications are working correctly.")
    else:
        print("\n✗ Some tests failed. Check the output above for details.")

    return tests_failed == 0


if __name__ == '__main__':
    # Add utils directory to path
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    success = main()
    sys.exit(0 if success else 1)
