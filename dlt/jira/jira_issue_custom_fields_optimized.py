"""
Jira Issue Custom Fields DLT Pipeline - OPTIMIZED VERSION

HIGH-PERFORMANCE extraction with:
- Parallel processing with 8 workers (increased from 4)
- Stores custom fields as JSON (one row per issue vs flattened rows)
- Minimal data transformation
- For daily mode: Only fetch issues updated in lookback period
- Aggressive timeout and retry settings

Pipeline Modes:
    - initial: Full replace with parallel extraction
    - daily: Replace mode - only updated issues

Performance improvements over original:
- Stores custom fields as JSON object per issue (not flattened)
- Fewer database rows to insert
- Faster extraction with more workers

Usage:
    docker exec ppm-dlt python /app/jira/jira_issue_custom_fields_optimized.py --mode=initial
    docker exec ppm-dlt python /app/jira/jira_issue_custom_fields_optimized.py --mode=daily
"""

import dlt
from dlt.common.schema.typing import TWriteDisposition
import requests
from requests.auth import HTTPBasicAuth
import os
import sys
import argparse
import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any
import time

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dlt_utils import sync_dlt_state_with_database

# ===== CONFIGURATION =====
TABLE_NAME = "issue_custom_fields"
SCHEMA_NAME = "raw_jira"
PIPELINE_NAME = "jira_issue_custom_fields_optimized"

# Performance settings - AGGRESSIVE
MAX_WORKERS = 8  # Increased from 4
BATCH_SIZE = 500  # Report progress
MAX_RETRIES = 2  # Reduced from 3
RETRY_DELAY = 1  # Reduced from 2
ISSUES_PER_PAGE = 100
REQUEST_TIMEOUT = 15

# Custom fields to extract
SELECTED_CUSTOM_FIELDS = [
    'customfield_10037',  # Story Points
    'customfield_10014',  # Epic Link
    'customfield_10100',  # Acceptance Criteria
    'customfield_10467',  # ITOPS Onaycı
    'customfield_10449',  # Bilgi Güvenliği Approver
    'customfield_10306',  # Kayıt Türü
    'customfield_10415',  # Approvers for FirmaX Operation Group
    'customfield_10176',  # NewSprintIssue
    'customfield_10284',  # IT/Diğer
    'customfield_10153',  # Approver/s (IT)
    'customfield_10019',  # Rank
    'customfield_10126',  # Approver/s
    'customfield_10000',  # development
    'customfield_10097',  # Spike Type
    'customfield_10150',  # Defect Tespit Süreci
    'customfield_10073',  # Bug Tespit Ortamı
    'customfield_11915',  # Project
    'customfield_10129',  # Product Choice
    'customfield_10020',  # Sprint
    'customfield_10349',  # Eylül 2024 Planlanan Efor
]


def generate_monthly_date_ranges(start_date: str, end_date: str = None) -> List[tuple]:
    """Generate monthly date ranges"""
    if not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')

    start = datetime.strptime(start_date.split('T')[0], '%Y-%m-%d')
    end = datetime.strptime(end_date.split('T')[0] if 'T' in end_date else end_date, '%Y-%m-%d')

    date_ranges = []
    current = start

    while current < end:
        if current.month == 12:
            next_month = current.replace(year=current.year + 1, month=1, day=1)
        else:
            next_month = current.replace(month=current.month + 1, day=1)

        range_end = min(next_month - timedelta(days=1), end)
        date_ranges.append((current.strftime('%Y-%m-%d'), range_end.strftime('%Y-%m-%d')))
        current = next_month

    return date_ranges


def fetch_issues_for_date_range(
    base_url: str, auth: HTTPBasicAuth,
    start_date: str, end_date: str,
    fields: List[str], range_idx: int, total_ranges: int
) -> List[Dict[str, Any]]:
    """Fetch issues for a date range"""
    jql = f"created >= '{start_date}' AND created <= '{end_date}' ORDER BY created ASC"
    url = f"{base_url}/rest/api/3/search/jql"

    all_issues = []
    next_page_token = None

    while True:
        params = {
            "jql": jql,
            "maxResults": ISSUES_PER_PAGE,
            "fields": ",".join(fields)
        }

        if next_page_token:
            params["nextPageToken"] = next_page_token

        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(url, auth=auth, params=params, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                data = response.json()
                issues = data.get("issues", [])
                all_issues.extend(issues)

                next_page_token = data.get("nextPageToken")
                if not next_page_token or not issues:
                    print(f"   [{range_idx + 1}/{total_ranges}] {start_date} to {end_date}: {len(all_issues)} issues")
                    sys.stdout.flush()
                    return all_issues

                break

            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                else:
                    print(f"   [{range_idx + 1}/{total_ranges}] Failed: {e}")
                    sys.stdout.flush()
                    return all_issues

    return all_issues


def fetch_all_issues_parallel(base_url: str, auth: HTTPBasicAuth, jira_start_date: str) -> List[Dict[str, Any]]:
    """Fetch ALL issues using parallel extraction (for initial load)"""
    jql_start_date = jira_start_date.split('T')[0]

    print(f"   Fetching ALL issues from {jql_start_date}...")
    print(f"   Strategy: Parallel extraction with {MAX_WORKERS} workers")
    sys.stdout.flush()

    date_ranges = generate_monthly_date_ranges(jql_start_date)
    total_ranges = len(date_ranges)
    print(f"   Generated {total_ranges} monthly date ranges")
    sys.stdout.flush()

    fields_to_fetch = ["key"] + SELECTED_CUSTOM_FIELDS
    all_issues = []

    start_time = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_range = {
            executor.submit(
                fetch_issues_for_date_range, base_url, auth, start, end,
                fields_to_fetch, idx, total_ranges
            ): (start, end, idx)
            for idx, (start, end) in enumerate(date_ranges)
        }

        for future in as_completed(future_to_range):
            try:
                issues = future.result()
                all_issues.extend(issues)
            except Exception as e:
                print(f"   Exception: {e}")
                sys.stdout.flush()

    elapsed = time.time() - start_time
    print(f"   Completed: Fetched {len(all_issues)} issues in {elapsed:.1f}s ({len(all_issues)/elapsed:.1f} issues/sec)")
    sys.stdout.flush()
    return all_issues


def fetch_updated_issues(base_url: str, auth: HTTPBasicAuth, lookback_days: int) -> List[Dict[str, Any]]:
    """Fetch issues updated in last N days (for daily load)"""
    lookback_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    jql = f"updated >= '{lookback_date}' ORDER BY updated DESC"

    print(f"   Fetching issues updated since {lookback_date}...")
    sys.stdout.flush()

    all_issues = []
    next_page_token = None
    fields_to_fetch = ["key"] + SELECTED_CUSTOM_FIELDS

    start_time = time.time()

    while True:
        url = f"{base_url}/rest/api/3/search/jql"
        params = {
            "jql": jql,
            "maxResults": ISSUES_PER_PAGE,
            "fields": ",".join(fields_to_fetch)
        }

        if next_page_token:
            params["nextPageToken"] = next_page_token

        try:
            response = requests.get(url, auth=auth, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            issues = data.get("issues", [])
            all_issues.extend(issues)

            total = data.get("total", len(all_issues))
            if len(all_issues) % BATCH_SIZE == 0:
                print(f"   Retrieved {len(all_issues)}/{total} issues")
                sys.stdout.flush()

            next_page_token = data.get("nextPageToken")
            if not next_page_token or not issues:
                break

        except Exception as e:
            print(f"   Error: {e}")
            sys.stdout.flush()
            raise

    elapsed = time.time() - start_time
    print(f"   Completed: Fetched {len(all_issues)} issues in {elapsed:.1f}s")
    sys.stdout.flush()
    return all_issues


def process_issue_custom_fields(issue: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process issue custom fields - OPTIMIZED.
    Returns ONE record per issue with custom fields as JSON.
    """
    fields = issue.get('fields', {})
    issue_key = issue.get('key')

    custom_fields_dict = {}
    field_count = 0

    for field_id in SELECTED_CUSTOM_FIELDS:
        value = fields.get(field_id)
        if value is not None:
            # Store value as-is (will be JSON serialized)
            custom_fields_dict[field_id] = value
            field_count += 1

    return {
        'id': f"issue_{issue_key}",  # Unique ID
        'issue_key': issue_key,
        'custom_fields': json.dumps(custom_fields_dict) if custom_fields_dict else None,
        'field_count': field_count,
        'extracted_at': datetime.utcnow().isoformat(),
        '_etl_date': datetime.now().isoformat()
    }


def run_pipeline(mode: str = "initial"):
    """Run the OPTIMIZED Jira issue custom fields pipeline."""
    print("=" * 80)
    print(f"Jira Issue Custom Fields Pipeline (OPTIMIZED) - Mode: {mode.upper()}")
    print("=" * 80)
    print(f"   Max workers: {MAX_WORKERS}")
    print(f"   Request timeout: {REQUEST_TIMEOUT}s")
    print(f"   Custom fields: {len(SELECTED_CUSTOM_FIELDS)}")
    print("=" * 80)
    sys.stdout.flush()

    # Get credentials
    base_url = os.getenv("JIRA_SUBDOMAIN", "").strip('"')
    email = os.getenv("JIRA_EMAIL", "").strip('"')
    api_token = os.getenv("JIRA_API_TOKEN", "").strip('"')

    if not base_url:
        base_url = os.getenv("SOURCES__JIRA__SUBDOMAIN", "").strip('"')
    if not email:
        email = os.getenv("SOURCES__JIRA__EMAIL", "").strip('"')
    if not api_token:
        api_token = os.getenv("SOURCES__JIRA__API_TOKEN", "").strip('"')

    if not all([base_url, email, api_token]):
        raise ValueError("Missing required environment variables")

    auth = HTTPBasicAuth(email, api_token)

    print("\nExtracting Data...")
    sys.stdout.flush()

    # Fetch issues based on mode
    if mode == "initial":
        jira_start_date = os.getenv("JIRA_START_DATE", "2024-01-01T00:00:00Z")
        print(f"   Initial mode: From {jira_start_date}")
        sys.stdout.flush()
        raw_issues = fetch_all_issues_parallel(base_url, auth, jira_start_date)
    else:
        lookback_days = int(os.getenv("JIRA_INCREMENTAL_DAYS", "30"))
        print(f"   Daily mode: Lookback {lookback_days} days")
        sys.stdout.flush()
        raw_issues = fetch_updated_issues(base_url, auth, lookback_days)

    if not raw_issues:
        print("\nNo issues found. Exiting.")
        sys.stdout.flush()
        return None

    print(f"\nFetched {len(raw_issues)} raw issues")
    sys.stdout.flush()

    # Process custom fields
    print("Processing custom fields...")
    sys.stdout.flush()
    all_custom_fields = [process_issue_custom_fields(issue) for issue in raw_issues]
    print(f"Processed {len(all_custom_fields)} issue records")
    sys.stdout.flush()

    # Create pipeline
    pipeline = dlt.pipeline(
        pipeline_name=PIPELINE_NAME,
        destination="postgres",
        dataset_name=SCHEMA_NAME
    )

    # Determine write mode: merge for first run (creates table), replace for subsequent runs
    from dlt_utils import table_exists
    table_found = table_exists(SCHEMA_NAME, TABLE_NAME)

    if table_found:
        write_disposition: TWriteDisposition = "replace"
        sync_dlt_state_with_database(pipeline, SCHEMA_NAME, TABLE_NAME)
        # Recreate pipeline after sync
        pipeline = dlt.pipeline(
            pipeline_name=PIPELINE_NAME,
            destination="postgres",
            dataset_name=SCHEMA_NAME
        )
    else:
        # Use merge mode for first run to create table, then it will be replaced next time
        write_disposition: TWriteDisposition = "merge"
        print(f"   📝 Table {SCHEMA_NAME}.{TABLE_NAME} does not exist - using MERGE mode to create")
        sys.stdout.flush()

    print(f"\nLoading to Database ({write_disposition} mode)...")
    sys.stdout.flush()

    load_info = pipeline.run(
        dlt.resource(
            all_custom_fields,
            name=TABLE_NAME,
            write_disposition=write_disposition,
            primary_key="id"
        )
    )

    # Verify success
    if load_info.has_failed_jobs:
        print("\n" + "=" * 80)
        print("LOAD FAILED!")
        print("=" * 80)
        for package in load_info.load_packages:
            for job in package.jobs.get("failed_jobs", []):
                print(f"   Failed: {job.file_path}")
                if hasattr(job, 'failed_message'):
                    print(f"   Error: {job.failed_message}")
        raise Exception("DLT load failed")

    print("\n" + "=" * 80)
    print("Jira Issue Custom Fields Load Completed (OPTIMIZED)!")
    print("=" * 80)
    print(f"   Pipeline: {load_info.pipeline.pipeline_name}")
    print(f"   Table: {SCHEMA_NAME}.{TABLE_NAME}")
    print(f"   Mode: {write_disposition}")
    print(f"   Records loaded: {len(all_custom_fields)}")
    print("=" * 80)
    sys.stdout.flush()

    return load_info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jira Issue Custom Fields DLT Pipeline (OPTIMIZED)")
    parser.add_argument(
        "--mode",
        choices=["initial", "daily"],
        default="initial",
        help="Pipeline mode"
    )
    args = parser.parse_args()

    run_pipeline(mode=args.mode)
