"""
Jira Issue Subtasks DLT Pipeline - OPTIMIZED VERSION

HIGH-PERFORMANCE extraction with:
- Parallel processing with configurable workers (default: 8)
- Connection pooling with requests.Session
- Concurrent subtask extraction for multiple issues
- Batch processing with real-time progress metrics
- Shorter timeouts with fast retries
- Thread-safe progress tracking

Pipeline Modes:
    - initial: Full extract using parallel extraction (all issues from JIRA_START_DATE)
    - daily: Extract subtasks for issues updated in last N days

Both modes use replace since subtask relationships are extracted fresh each time.

Usage:
    docker exec ppm-dlt python /app/jira/jira_issue_subtasks_optimized.py --mode=initial
    docker exec ppm-dlt python /app/jira/jira_issue_subtasks_optimized.py --mode=daily
    docker exec ppm-dlt python /app/jira/jira_issue_subtasks_optimized.py --mode=initial --max-workers=16
"""

import dlt
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from requests.auth import HTTPBasicAuth
import os
import sys
import argparse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any
import time
import threading

# Force unbuffered output for real-time logging
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dlt_utils import sync_dlt_state_with_database

# ===== CONFIGURATION =====
TABLE_NAME = "issue_subtasks"
SCHEMA_NAME = "raw_jira"
PIPELINE_NAME = "jira_issue_subtasks_optimized"

# Performance settings - OPTIMIZED
MAX_WORKERS = 8  # Parallel workers for issue fetching
BATCH_SIZE = 100  # Report progress every N issues
MAX_RETRIES = 2  # Reduced from 3 for faster failure
RETRY_DELAY = 0.5  # Reduced delay
REQUEST_TIMEOUT = 30  # Request timeout
ISSUES_PER_PAGE = 100
CONNECTION_POOL_SIZE = 10  # Connection pool per thread

# Thread-local storage for session objects
thread_local = threading.local()


# Thread-safe counter for progress tracking
class ProgressTracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.issues_processed = 0
        self.subtasks_collected = 0

    def update(self, subtasks_count: int):
        with self.lock:
            self.issues_processed += 1
            self.subtasks_collected += subtasks_count
            return self.issues_processed, self.subtasks_collected


def create_session(auth: HTTPBasicAuth) -> requests.Session:
    """Create a session with connection pooling and retry logic."""
    session = requests.Session()
    session.auth = auth
    session.headers.update({"Accept": "application/json"})

    # Configure retry strategy
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=RETRY_DELAY,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )

    adapter = HTTPAdapter(
        pool_connections=CONNECTION_POOL_SIZE,
        pool_maxsize=CONNECTION_POOL_SIZE,
        max_retries=retry_strategy
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


def get_session(auth: HTTPBasicAuth) -> requests.Session:
    """Get thread-local session (creates one if doesn't exist)."""
    if not hasattr(thread_local, "session"):
        thread_local.session = create_session(auth)
    return thread_local.session


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
    range_idx: int, total_ranges: int
) -> List[Dict[str, Any]]:
    """Fetch issues for a specific date range with subtasks using session pooling"""
    jql = f"created >= '{start_date}' AND created <= '{end_date}' ORDER BY created ASC"
    url = f"{base_url}/rest/api/3/search/jql"

    session = get_session(auth)
    all_issues = []
    next_page_token = None

    while True:
        params = {
            "jql": jql,
            "maxResults": ISSUES_PER_PAGE,
            "fields": "key,subtasks"
        }

        if next_page_token:
            params["nextPageToken"] = next_page_token

        try:
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            issues = data.get("issues", [])
            all_issues.extend(issues)

            next_page_token = data.get("nextPageToken")
            if not next_page_token or not issues:
                print(f"   [{range_idx + 1}/{total_ranges}] {start_date} to {end_date}: {len(all_issues)} issues")
                sys.stdout.flush()
                return all_issues

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:  # Rate limit
                retry_after = int(e.response.headers.get('Retry-After', 10))
                print(f"   [{range_idx + 1}/{total_ranges}] Rate limited. Waiting {retry_after} seconds...")
                sys.stdout.flush()
                time.sleep(retry_after)
                continue
            else:
                print(f"   [{range_idx + 1}/{total_ranges}] Failed: {e}")
                sys.stdout.flush()
                return all_issues
        except Exception as e:
            print(f"   [{range_idx + 1}/{total_ranges}] Failed: {e}")
            sys.stdout.flush()
            return all_issues

    return all_issues


def fetch_all_issues_parallel(base_url: str, auth: HTTPBasicAuth, jira_start_date: str, max_workers: int) -> List[Dict[str, Any]]:
    """Fetch ALL issues using parallel extraction with configurable workers"""
    jql_start_date = jira_start_date.split('T')[0]

    print(f"   Fetching ALL issues (from {jql_start_date})...")
    print(f"   Strategy: Parallel extraction with {max_workers} workers")
    sys.stdout.flush()

    date_ranges = generate_monthly_date_ranges(jql_start_date)
    total_ranges = len(date_ranges)
    print(f"   Generated {total_ranges} monthly date ranges")
    sys.stdout.flush()

    all_issues = []
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_range = {
            executor.submit(
                fetch_issues_for_date_range, base_url, auth, start, end, idx, total_ranges
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
    rate = len(all_issues) / elapsed if elapsed > 0 else 0
    print(f"   Completed: Fetched {len(all_issues)} total issues in {elapsed:.1f}s ({rate:.1f} issues/sec)")
    sys.stdout.flush()
    return all_issues


def fetch_updated_issues(base_url: str, auth: HTTPBasicAuth, lookback_days: int) -> List[Dict[str, Any]]:
    """Fetch issues updated in the last N days using session pooling"""
    lookback_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    jql = f"updated >= '{lookback_date}' ORDER BY updated DESC"

    print(f"   Fetching issues updated since {lookback_date}...")
    sys.stdout.flush()

    session = create_session(auth)
    all_issues = []
    next_page_token = None

    while True:
        url = f"{base_url}/rest/api/3/search/jql"
        params = {
            "jql": jql,
            "maxResults": ISSUES_PER_PAGE,
            "fields": "key,subtasks"
        }

        if next_page_token:
            params["nextPageToken"] = next_page_token

        try:
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            issues = data.get("issues", [])
            all_issues.extend(issues)

            total = data.get("total", len(all_issues))
            print(f"   Retrieved {len(all_issues)}/{total} issues")
            sys.stdout.flush()

            next_page_token = data.get("nextPageToken")
            if not next_page_token or not issues:
                break

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:  # Rate limit
                retry_after = int(e.response.headers.get('Retry-After', 10))
                print(f"   Rate limited. Waiting {retry_after} seconds...")
                sys.stdout.flush()
                time.sleep(retry_after)
                continue
            else:
                print(f"   Error: {e}")
                sys.stdout.flush()
                raise
        except Exception as e:
            print(f"   Error: {e}")
            sys.stdout.flush()
            raise

    session.close()
    return all_issues


def extract_subtasks_from_single_issue(issue: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract subtasks from a single issue - designed for parallel processing"""
    fields = issue.get('fields', {})
    subtasks = fields.get('subtasks', [])

    records = []
    for st in subtasks:
        record = {
            'parent_key': issue.get('key'),
            'subtask_key': st.get('key'),
            'subtask_summary': st.get('fields', {}).get('summary'),
            'subtask_status': st.get('fields', {}).get('status', {}).get('name'),
            '_etl_date': datetime.now().isoformat()
        }
        records.append(record)

    return records


def extract_subtasks_parallel(issues: List[Dict[str, Any]], max_workers: int) -> List[Dict[str, Any]]:
    """Extract subtasks from multiple issues using PARALLEL processing"""
    if not issues:
        return []

    print(f"\nProcessing subtasks...")
    print(f"   Processing {len(issues)} issues with {max_workers} workers...")
    sys.stdout.flush()

    all_subtasks = []
    tracker = ProgressTracker()
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_issue = {
            executor.submit(extract_subtasks_from_single_issue, issue): issue
            for issue in issues
        }

        # Collect results as they complete
        for future in as_completed(future_to_issue):
            try:
                subtasks = future.result()
                if subtasks:
                    all_subtasks.extend(subtasks)

                issues_processed, subtasks_collected = tracker.update(len(subtasks))

                # Progress reporting
                if issues_processed % BATCH_SIZE == 0 or issues_processed == len(issues):
                    elapsed = time.time() - start_time
                    rate = issues_processed / elapsed if elapsed > 0 else 0
                    print(f"   Progress: {issues_processed}/{len(issues)} issues, {subtasks_collected} subtasks ({rate:.1f} issues/sec)")
                    sys.stdout.flush()

            except Exception as e:
                print(f"   Exception processing issue: {e}")
                sys.stdout.flush()

    elapsed = time.time() - start_time
    rate = len(issues) / elapsed if elapsed > 0 else 0
    print(f"   Completed: {len(issues)} issues in {elapsed:.1f}s ({rate:.1f} issues/sec, {len(all_subtasks)} subtasks)")
    sys.stdout.flush()

    return all_subtasks


def run_pipeline(mode: str = "initial", max_workers: int = MAX_WORKERS):
    """Run the OPTIMIZED Jira issue subtasks pipeline."""
    print("=" * 80)
    print(f"Jira Issue Subtasks Pipeline (OPTIMIZED) - Mode: {mode.upper()}")
    print("=" * 80)
    print(f"   Max workers: {max_workers}")
    print(f"   Request timeout: {REQUEST_TIMEOUT}s")
    print(f"   Max retries: {MAX_RETRIES}")
    print(f"   Connection pool: {CONNECTION_POOL_SIZE}")
    print(f"   Batch size: {BATCH_SIZE}")
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

    # Fetch issues based on mode
    print("\nExtracting Data...")
    sys.stdout.flush()

    if mode == "initial":
        jira_start_date = os.getenv("JIRA_START_DATE", "2024-01-01T00:00:00Z")
        print(f"Mode: INITIAL - Full extract from {jira_start_date}")
        sys.stdout.flush()
        raw_issues = fetch_all_issues_parallel(base_url, auth, jira_start_date, max_workers)
    else:
        lookback_days = int(os.getenv("JIRA_INCREMENTAL_DAYS", "30"))
        print(f"Mode: DAILY - Lookback {lookback_days} days")
        sys.stdout.flush()
        raw_issues = fetch_updated_issues(base_url, auth, lookback_days)

    print(f"\nFetched {len(raw_issues)} issues")
    sys.stdout.flush()

    if not raw_issues:
        print("\nNo issues found. Exiting.")
        sys.stdout.flush()
        return None

    # Extract subtasks using PARALLEL processing
    all_subtasks = extract_subtasks_parallel(raw_issues, max_workers)

    print(f"\nExtracted {len(all_subtasks)} subtask relationships")
    sys.stdout.flush()

    # Create pipeline
    pipeline = dlt.pipeline(
        pipeline_name=PIPELINE_NAME,
        destination="postgres",
        dataset_name=SCHEMA_NAME
    )

    # Sync state and load
    sync_dlt_state_with_database(pipeline, SCHEMA_NAME, TABLE_NAME)
    pipeline = dlt.pipeline(
        pipeline_name=PIPELINE_NAME,
        destination="postgres",
        dataset_name=SCHEMA_NAME
    )

    print(f"\nLoading to Database (replace mode)...")
    sys.stdout.flush()

    load_info = pipeline.run(
        dlt.resource(all_subtasks, name=TABLE_NAME, write_disposition="replace")
    )

    if load_info.has_failed_jobs:
        raise Exception("DLT load failed with failed jobs")

    print("\n" + "=" * 80)
    print("Jira Issue Subtasks Load Completed (OPTIMIZED)!")
    print("=" * 80)
    print(f"   Pipeline: {PIPELINE_NAME}")
    print(f"   Table: {SCHEMA_NAME}.{TABLE_NAME}")
    print(f"   Records: {len(all_subtasks)}")
    print(f"   Mode: {mode}")
    print(f"   Max workers used: {max_workers}")
    print("=" * 80)
    sys.stdout.flush()

    return load_info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jira Issue Subtasks DLT Pipeline (OPTIMIZED)")
    parser.add_argument("--mode", choices=["initial", "daily"], default="initial",
                        help="Pipeline mode: initial (full extract) or daily (incremental)")
    parser.add_argument("--max-workers", type=int, default=MAX_WORKERS,
                        help=f"Maximum parallel workers (default: {MAX_WORKERS})")
    args = parser.parse_args()

    run_pipeline(mode=args.mode, max_workers=args.max_workers)
