"""
Jira Worklogs DLT Pipeline - OPTIMIZED VERSION WITH FULL PAGINATION

HIGH-PERFORMANCE extraction with:
- Parallel processing with configurable workers (default: 8)
- Concurrent worklog fetching for multiple issues
- FULL PAGINATION SUPPORT for worklogs (handles >5000 worklogs per issue)
- Parallel date range processing for initial mode
- Minimal blocking with ThreadPoolExecutor
- Rate limit handling (429 responses)
- Real-time performance metrics

Pipeline Modes:
    - initial: Full extract with parallel day-by-day chunking
    - daily: Extract worklogs updated in last N days using bulk API

Filtering Options (all optional, can be combined):
    - start_date/end_date: Date range filter (YYYY-MM-DD)
    - issue_key: Filter by specific issue key (e.g., "PROJ-123")
    - issue_id: Filter by issue ID
    - author_id: Filter by author account ID
    - worklog_id: Fetch specific worklog ID(s) directly

Key optimizations:
    - Multi-threaded issue worklog fetching (8x faster)
    - Parallel date range processing (configurable)
    - Complete pagination for all Jira endpoints (no data truncation)
    - Batch commits per chunk with merge strategy
    - Real-time throughput monitoring

Usage:
    docker exec ppm-dlt python /app/jira/jira_worklogs_optimized.py --mode=initial
    docker exec ppm-dlt python /app/jira/jira_worklogs_optimized.py --mode=daily
    docker exec ppm-dlt python /app/jira/jira_worklogs_optimized.py --mode=initial --max-workers=16

    # With optional filters:
    docker exec ppm-dlt python /app/jira/jira_worklogs_optimized.py --issue-key=PROJ-123
    docker exec ppm-dlt python /app/jira/jira_worklogs_optimized.py --author-id=5b10ac8d82e05b22cc7d4ef5
    docker exec ppm-dlt python /app/jira/jira_worklogs_optimized.py --worklog-id=10000,10001,10002
    docker exec ppm-dlt python /app/jira/jira_worklogs_optimized.py --issue-key=PROJ-123 --start-date=2024-01-01 --end-date=2024-12-31
"""

import dlt
import requests
from requests.auth import HTTPBasicAuth
import os
import sys
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Any
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Force unbuffered output for real-time logging
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dlt_utils import sync_dlt_state_with_database

# ===== CONFIGURATION =====
TABLE_NAME = "worklogs"
SCHEMA_NAME = "raw_jira"
PIPELINE_NAME = "jira_worklogs_optimized"

# Performance settings - OPTIMIZED
MAX_WORKERS = 8  # Parallel workers for issue worklog fetching
DATE_RANGE_WORKERS = 2  # Parallel workers for date range processing (keep low to avoid API rate limits)
BATCH_SIZE = 50  # Report progress every N issues
MAX_RETRIES = 2  # Reduced from 3 for faster failure
RETRY_DELAY = 1  # Reduced from 2 seconds
REQUEST_TIMEOUT = 15  # Increased to 15 seconds for large responses
ISSUES_PER_CHUNK = 500  # Process issues in chunks
DAYS_PER_CHUNK = 5  # Use 5-day chunks for initial load

# Worklog pagination settings (CRITICAL for handling >5000 worklogs per issue)
WORKLOG_PAGE_SIZE = 1000  # Max allowed by Jira API per page
ISSUE_PAGE_SIZE = 100  # For issue search pagination

# Thread-safe counter for progress tracking
class ProgressTracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.issues_processed = 0
        self.worklogs_collected = 0

    def update(self, worklogs_count: int):
        with self.lock:
            self.issues_processed += 1
            self.worklogs_collected += worklogs_count
            return self.issues_processed, self.worklogs_collected


# Worklog fields to extract
SELECTED_FIELDS = [
    "id",
    "issueId",
    "author",
    "updateAuthor",
    "comment",
    "created",
    "updated",
    "started",
    "timeSpent",
    "timeSpentSeconds"
]


def flatten_worklog(worklog: Dict[str, Any], issue_key: str = None, issue_id: str = None) -> Dict[str, Any]:
    """Flatten worklog record with selected fields"""
    flattened = {
        'id': worklog.get('id'),
        'issue_id': issue_id or worklog.get('issueId'),
        'issue_key': issue_key or worklog.get('issue_key'),
        'created': worklog.get('created'),
        'updated': worklog.get('updated'),
        'started': worklog.get('started'),
        'time_spent': worklog.get('timeSpent'),
        'time_spent_seconds': worklog.get('timeSpentSeconds'),
    }

    # Flatten author
    author = worklog.get('author', {})
    if author and isinstance(author, dict):
        flattened['author_id'] = author.get('accountId')
        flattened['author_name'] = author.get('displayName')

    # Flatten update author
    update_author = worklog.get('updateAuthor', {})
    if update_author and isinstance(update_author, dict):
        flattened['update_author_id'] = update_author.get('accountId')
        flattened['update_author_name'] = update_author.get('displayName')

    flattened['_etl_date'] = datetime.now().isoformat()

    return flattened


def fetch_issues_for_date_range(
    base_url: str,
    auth: HTTPBasicAuth,
    start_date: str,
    end_date: str
) -> List[Dict[str, Any]]:
    """
    Fetch issues with worklogs within a specific date range using startAt pagination.
    """
    jql = f"worklogDate >= '{start_date}' AND worklogDate < '{end_date}' ORDER BY created ASC"

    all_issues = []
    start_at = 0
    max_results = ISSUE_PAGE_SIZE

    while True:
        url = f"{base_url}/rest/api/3/search/jql"
        params = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": max_results,
            "fields": "key,id"
        }

        try:
            response = requests.get(url, auth=auth, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            issues = data.get("issues", [])
            total = data.get("total", 0)
            all_issues.extend(issues)

            # Check if we've retrieved all issues
            if start_at + len(issues) >= total or not issues:
                break

            # Update startAt for next page
            start_at += len(issues)

            # Small delay to avoid rate limiting
            time.sleep(0.1)

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:  # Rate limit
                retry_after = int(e.response.headers.get('Retry-After', 10))
                print(f"      Rate limited. Waiting {retry_after} seconds...")
                sys.stdout.flush()
                time.sleep(retry_after)
                continue
            else:
                print(f"      Error fetching issues: {e}")
                sys.stdout.flush()
                break
        except Exception as e:
            print(f"      Exception fetching issues: {e}")
            sys.stdout.flush()
            break

    return all_issues


def fetch_worklog_for_single_issue(
    base_url: str,
    auth: HTTPBasicAuth,
    issue: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Fetch worklogs for a SINGLE issue with FULL PAGINATION support.
    This function is designed to be called in parallel.
    Handles issues with >1000 worklogs by paginating through all pages.
    """
    issue_key = issue.get("key")
    issue_id = issue.get("id")
    all_worklogs = []

    if not issue_key:
        return all_worklogs

    for attempt in range(MAX_RETRIES):
        try:
            start_at = 0
            max_results = WORKLOG_PAGE_SIZE
            total_worklogs = 0

            while True:
                url = f"{base_url}/rest/api/3/issue/{issue_key}/worklog"
                params = {
                    "startAt": start_at,
                    "maxResults": max_results
                }

                response = requests.get(url, auth=auth, params=params, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                data = response.json()

                raw_worklogs = data.get("worklogs", [])
                total = data.get("total", 0)

                # Set total worklogs on first request
                if start_at == 0:
                    total_worklogs = total
                    if total_worklogs > WORKLOG_PAGE_SIZE:
                        print(f"      Issue {issue_key}: Found {total_worklogs} worklogs (will paginate)")
                        sys.stdout.flush()

                for worklog in raw_worklogs:
                    flattened = flatten_worklog(worklog, issue_key, issue_id)
                    all_worklogs.append(flattened)

                # Check if we've retrieved all worklogs
                if start_at + len(raw_worklogs) >= total or not raw_worklogs:
                    break

                # Update startAt for next page
                start_at += len(raw_worklogs)

                # Small delay to avoid rate limiting
                time.sleep(0.05)

                # Progress update for large datasets
                if total_worklogs > 1000 and start_at % 5000 == 0:
                    print(f"      Issue {issue_key}: Retrieved {start_at}/{total_worklogs} worklogs")
                    sys.stdout.flush()

            break  # Success, exit retry loop

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:  # Rate limit
                retry_after = int(e.response.headers.get('Retry-After', 10))
                print(f"      Issue {issue_key}: Rate limited. Waiting {retry_after} seconds...")
                sys.stdout.flush()
                time.sleep(retry_after)
                continue  # Retry the current page

            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                print(f"      Issue {issue_key}: Failed after {MAX_RETRIES} attempts: {e}")
                sys.stdout.flush()
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                print(f"      Issue {issue_key}: Failed after {MAX_RETRIES} attempts: {e}")
                sys.stdout.flush()

    return all_worklogs


def fetch_worklogs_for_issues_parallel(
    base_url: str,
    auth: HTTPBasicAuth,
    issues: List[Dict[str, Any]],
    max_workers: int = MAX_WORKERS,
    show_progress: bool = True
) -> List[Dict[str, Any]]:
    """
    Fetch worklogs for multiple issues using PARALLEL processing.
    This is the KEY optimization - processes multiple issues simultaneously.
    """
    if not issues:
        return []

    all_worklogs = []
    total_issues = len(issues)
    tracker = ProgressTracker()
    start_time = time.time()

    if show_progress:
        print(f"      Processing {total_issues} issues with {max_workers} workers...")
        sys.stdout.flush()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_issue = {
            executor.submit(fetch_worklog_for_single_issue, base_url, auth, issue): issue
            for issue in issues
        }

        # Collect results as they complete
        for future in as_completed(future_to_issue):
            try:
                worklogs = future.result()
                if worklogs:
                    all_worklogs.extend(worklogs)

                issues_processed, worklogs_collected = tracker.update(len(worklogs))

                # Progress reporting
                if show_progress and (issues_processed % BATCH_SIZE == 0 or issues_processed == total_issues):
                    elapsed = time.time() - start_time
                    rate = issues_processed / elapsed if elapsed > 0 else 0
                    print(f"      Progress: {issues_processed}/{total_issues} issues, {worklogs_collected} worklogs ({rate:.1f} issues/sec)")
                    sys.stdout.flush()

            except Exception as e:
                print(f"      Exception processing issue: {e}")
                sys.stdout.flush()

    elapsed = time.time() - start_time
    if show_progress:
        print(f"      Completed: {total_issues} issues in {elapsed:.1f}s ({total_issues/elapsed:.1f} issues/sec, {len(all_worklogs)} worklogs)")
        sys.stdout.flush()

    return all_worklogs


def generate_date_ranges(start_date: str, end_date: str, days_per_chunk: int = 5) -> List[tuple]:
    """
    Generate date ranges for chunked extraction.
    Returns list of (start_date, end_date) tuples.
    """
    ranges = []
    start = datetime.strptime(start_date.split('T')[0], '%Y-%m-%d')
    end = datetime.strptime(end_date.split('T')[0], '%Y-%m-%d')

    current = start
    while current < end:
        chunk_end = min(current + timedelta(days=days_per_chunk), end)
        ranges.append((
            current.strftime('%Y-%m-%d'),
            chunk_end.strftime('%Y-%m-%d')
        ))
        current = chunk_end

    return ranges


def extract_worklogs_for_date_range(
    base_url: str,
    auth: HTTPBasicAuth,
    range_start: str,
    range_end: str,
    max_workers: int = MAX_WORKERS
) -> List[Dict[str, Any]]:
    """
    Extract all worklogs for a specific date range using parallel processing.
    Returns list of worklog dictionaries.
    """
    all_worklogs = []

    # Fetch issues for this date range
    issues = fetch_issues_for_date_range(base_url, auth, range_start, range_end)

    if not issues:
        return all_worklogs

    print(f"      Found {len(issues)} issues")
    sys.stdout.flush()

    # Process issues in chunks with parallel worklog fetching
    for chunk_start in range(0, len(issues), ISSUES_PER_CHUNK):
        chunk_end = min(chunk_start + ISSUES_PER_CHUNK, len(issues))
        issue_chunk = issues[chunk_start:chunk_end]

        print(f"      Processing issue chunk {chunk_start//ISSUES_PER_CHUNK + 1}/{(len(issues)-1)//ISSUES_PER_CHUNK + 1} ({len(issue_chunk)} issues)...")
        sys.stdout.flush()

        # Fetch worklogs for this chunk using PARALLEL processing
        worklogs = fetch_worklogs_for_issues_parallel(
            base_url, auth, issue_chunk,
            max_workers=max_workers,
            show_progress=True
        )
        all_worklogs.extend(worklogs)

    return all_worklogs


def process_single_date_range(
    args: tuple
) -> tuple:
    """
    Process a single date range - designed for parallel execution.
    Returns (range_index, range_start, range_end, worklogs)
    """
    range_idx, range_start, range_end, base_url, auth, max_workers = args

    print(f"   [Thread {range_idx + 1}] Processing range: {range_start} to {range_end}")
    sys.stdout.flush()

    worklogs = extract_worklogs_for_date_range(
        base_url, auth, range_start, range_end, max_workers
    )

    print(f"   [Thread {range_idx + 1}] Completed: {len(worklogs)} worklogs")
    sys.stdout.flush()

    return (range_idx, range_start, range_end, worklogs)


def get_worklog_ids_updated_since(base_url: str, auth: HTTPBasicAuth, since_timestamp: int) -> List[int]:
    """Get worklog IDs updated since timestamp using bulk API"""
    url = f"{base_url}/rest/api/3/worklog/updated"
    all_worklog_ids = []

    params = {"since": since_timestamp}

    while True:
        try:
            response = requests.get(url, auth=auth, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            values = data.get("values", [])
            for item in values:
                worklog_id = item.get("worklogId")
                if worklog_id:
                    all_worklog_ids.append(worklog_id)

            print(f"   Retrieved {len(all_worklog_ids)} worklog IDs...")
            sys.stdout.flush()

            if data.get("lastPage", True):
                break

            next_page = data.get("nextPage")
            if next_page:
                url = next_page
                params = {}
            else:
                until = data.get("until")
                if until:
                    params = {"since": until}
                else:
                    break

        except Exception as e:
            print(f"   Error fetching worklog IDs: {e}")
            sys.stdout.flush()
            break

    return all_worklog_ids


def fetch_worklogs_by_ids_parallel(
    base_url: str,
    auth: HTTPBasicAuth,
    worklog_ids: List[int],
    max_workers: int = MAX_WORKERS
) -> List[Dict[str, Any]]:
    """
    Fetch worklog details in bulk with parallel batch processing.
    """
    if not worklog_ids:
        return []

    url = f"{base_url}/rest/api/3/worklog/list"
    all_worklogs = []

    batch_size = 1000
    total_batches = (len(worklog_ids) + batch_size - 1) // batch_size

    print(f"   Fetching {len(worklog_ids)} worklogs in {total_batches} batches...")
    sys.stdout.flush()

    def fetch_batch(batch_num: int, batch_ids: List[int]) -> List[Dict[str, Any]]:
        """Fetch a single batch of worklogs"""
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.post(
                    url, auth=auth, json={"ids": batch_ids},
                    headers={"Content-Type": "application/json"},
                    timeout=REQUEST_TIMEOUT
                )
                response.raise_for_status()
                worklogs = response.json()

                batch_results = []
                for worklog in worklogs:
                    flattened = flatten_worklog(worklog)
                    batch_results.append(flattened)

                print(f"   Batch {batch_num + 1}/{total_batches}: {len(batch_results)} worklogs")
                sys.stdout.flush()
                return batch_results

            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                else:
                    print(f"   Error fetching batch {batch_num + 1}: {e}")
                    sys.stdout.flush()
                    return []
        return []

    # Process batches in parallel
    with ThreadPoolExecutor(max_workers=min(max_workers, total_batches)) as executor:
        futures = []
        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(worklog_ids))
            batch_ids = worklog_ids[start_idx:end_idx]

            future = executor.submit(fetch_batch, batch_num, batch_ids)
            futures.append(future)

        # Collect results
        for future in as_completed(futures):
            try:
                batch_results = future.result()
                all_worklogs.extend(batch_results)
            except Exception as e:
                print(f"   Exception in batch processing: {e}")
                sys.stdout.flush()

    return all_worklogs


def fetch_worklogs_for_single_issue_key(
    base_url: str,
    auth: HTTPBasicAuth,
    issue_key: str,
    start_date: str = None,
    end_date: str = None
) -> List[Dict[str, Any]]:
    """
    Fetch all worklogs for a specific issue key with FULL PAGINATION.
    Optionally filter by date range (started date).
    """
    all_worklogs = []
    issue_id = None

    print(f"   Fetching worklogs for issue: {issue_key}")
    sys.stdout.flush()

    # First get issue ID
    try:
        issue_url = f"{base_url}/rest/api/3/issue/{issue_key}?fields=id"
        issue_response = requests.get(issue_url, auth=auth, timeout=REQUEST_TIMEOUT)
        if issue_response.status_code == 200:
            issue_data = issue_response.json()
            issue_id = issue_data.get("id")
        elif issue_response.status_code == 404:
            print(f"   Issue {issue_key} not found")
            sys.stdout.flush()
            return []
    except Exception as e:
        print(f"   Error fetching issue details for {issue_key}: {e}")
        sys.stdout.flush()

    # Now fetch worklogs with pagination
    for attempt in range(MAX_RETRIES):
        try:
            start_at = 0
            max_results = WORKLOG_PAGE_SIZE
            total_worklogs = 0
            all_worklogs = []  # Reset on each retry

            while True:
                url = f"{base_url}/rest/api/3/issue/{issue_key}/worklog"
                params = {
                    "startAt": start_at,
                    "maxResults": max_results
                }

                response = requests.get(url, auth=auth, params=params, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                data = response.json()

                raw_worklogs = data.get("worklogs", [])
                total = data.get("total", 0)

                # Set total worklogs on first request
                if start_at == 0:
                    total_worklogs = total
                    print(f"   Total worklogs in Jira for {issue_key}: {total_worklogs}")
                    sys.stdout.flush()

                for worklog in raw_worklogs:
                    # Filter by date range if provided
                    if start_date or end_date:
                        started = worklog.get("started", "")
                        started_date = started.split("T")[0] if started else ""

                        if start_date and started_date < start_date:
                            continue
                        if end_date and started_date >= end_date:
                            continue

                    flattened = flatten_worklog(worklog, issue_key, issue_id)
                    all_worklogs.append(flattened)

                # Check if we've retrieved all worklogs
                if start_at + len(raw_worklogs) >= total or not raw_worklogs:
                    break

                # Update startAt for next page
                start_at += len(raw_worklogs)

                # Small delay to avoid rate limiting
                time.sleep(0.05)

                # Progress update for large datasets
                if total_worklogs > 1000 and start_at % 2000 == 0:
                    print(f"   Progress: Retrieved {start_at}/{total_worklogs} worklogs from {issue_key}")
                    sys.stdout.flush()

            if start_date or end_date:
                print(f"   Found {len(all_worklogs)} worklogs for {issue_key} (filtered from {total_worklogs} total)")
            else:
                print(f"   Found {len(all_worklogs)} worklogs for {issue_key}")
            sys.stdout.flush()
            break

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:  # Rate limit
                retry_after = int(e.response.headers.get('Retry-After', 10))
                print(f"   Rate limited. Waiting {retry_after} seconds...")
                sys.stdout.flush()
                time.sleep(retry_after)
                continue
            if e.response.status_code == 404:
                print(f"   Issue {issue_key} not found")
                sys.stdout.flush()
                break
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                print(f"   Error fetching worklogs for {issue_key}: {e}")
                sys.stdout.flush()
        except Exception as e:
            print(f"   Error fetching worklogs for {issue_key}: {e}")
            sys.stdout.flush()
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))

    return all_worklogs


def fetch_worklogs_for_issue_id(
    base_url: str,
    auth: HTTPBasicAuth,
    issue_id: str,
    start_date: str = None,
    end_date: str = None
) -> List[Dict[str, Any]]:
    """
    Fetch all worklogs for a specific issue ID with FULL PAGINATION.
    Optionally filter by date range (started date).
    """
    all_worklogs = []
    issue_key = None

    print(f"   Fetching worklogs for issue ID: {issue_id}")
    sys.stdout.flush()

    # First get the issue key
    try:
        issue_url = f"{base_url}/rest/api/3/issue/{issue_id}?fields=key"
        issue_response = requests.get(issue_url, auth=auth, timeout=REQUEST_TIMEOUT)
        if issue_response.status_code == 200:
            issue_data = issue_response.json()
            issue_key = issue_data.get("key")
        elif issue_response.status_code == 404:
            print(f"   Issue ID {issue_id} not found")
            sys.stdout.flush()
            return []
    except Exception as e:
        print(f"   Error fetching issue details for ID {issue_id}: {e}")
        sys.stdout.flush()

    # Now fetch worklogs with pagination
    for attempt in range(MAX_RETRIES):
        try:
            start_at = 0
            max_results = WORKLOG_PAGE_SIZE
            total_worklogs = 0
            all_worklogs = []  # Reset on each retry

            while True:
                url = f"{base_url}/rest/api/3/issue/{issue_id}/worklog"
                params = {
                    "startAt": start_at,
                    "maxResults": max_results
                }

                response = requests.get(url, auth=auth, params=params, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                data = response.json()

                raw_worklogs = data.get("worklogs", [])
                total = data.get("total", 0)

                # Set total worklogs on first request
                if start_at == 0:
                    total_worklogs = total
                    print(f"   Total worklogs in Jira for issue ID {issue_id}: {total_worklogs}")
                    sys.stdout.flush()

                for worklog in raw_worklogs:
                    # Filter by date range if provided
                    if start_date or end_date:
                        started = worklog.get("started", "")
                        started_date = started.split("T")[0] if started else ""

                        if start_date and started_date < start_date:
                            continue
                        if end_date and started_date >= end_date:
                            continue

                    flattened = flatten_worklog(worklog, issue_key, issue_id)
                    all_worklogs.append(flattened)

                # Check if we've retrieved all worklogs
                if start_at + len(raw_worklogs) >= total or not raw_worklogs:
                    break

                # Update startAt for next page
                start_at += len(raw_worklogs)

                # Small delay to avoid rate limiting
                time.sleep(0.05)

                # Progress update for large datasets
                if total_worklogs > 1000 and start_at % 2000 == 0:
                    print(f"   Progress: Retrieved {start_at}/{total_worklogs} worklogs for issue ID {issue_id}")
                    sys.stdout.flush()

            if start_date or end_date:
                print(f"   Found {len(all_worklogs)} worklogs for issue ID {issue_id} (filtered from {total_worklogs} total)")
            else:
                print(f"   Found {len(all_worklogs)} worklogs for issue ID {issue_id}")
            sys.stdout.flush()
            break

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:  # Rate limit
                retry_after = int(e.response.headers.get('Retry-After', 10))
                print(f"   Rate limited. Waiting {retry_after} seconds...")
                sys.stdout.flush()
                time.sleep(retry_after)
                continue
            if e.response.status_code == 404:
                print(f"   Issue ID {issue_id} not found")
                sys.stdout.flush()
                break
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                print(f"   Error fetching worklogs for issue ID {issue_id}: {e}")
                sys.stdout.flush()
        except Exception as e:
            print(f"   Error fetching worklogs for issue ID {issue_id}: {e}")
            sys.stdout.flush()
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))

    return all_worklogs


def build_jql_with_filters(
    start_date: str = None,
    end_date: str = None,
    issue_key: str = None,
    issue_keys: List[str] = None,
    author_id: str = None
) -> str:
    """
    Build JQL query dynamically based on provided filters.
    All filters are optional and can be combined.
    """
    conditions = []

    # Issue key filter (single or multiple)
    if issue_key:
        conditions.append(f'key = "{issue_key}"')
    elif issue_keys:
        keys_str = ", ".join([f'"{k}"' for k in issue_keys])
        conditions.append(f'key IN ({keys_str})')

    # Date range filter
    if start_date and end_date:
        conditions.append(f"worklogDate >= '{start_date}' AND worklogDate < '{end_date}'")
    elif start_date:
        conditions.append(f"worklogDate >= '{start_date}'")
    elif end_date:
        conditions.append(f"worklogDate < '{end_date}'")

    # Author filter
    if author_id:
        conditions.append(f'worklogAuthor = "{author_id}"')

    if not conditions:
        # Default: no filters
        return "ORDER BY created ASC"

    jql = " AND ".join(conditions) + " ORDER BY created ASC"
    return jql


def fetch_issues_with_filters(
    base_url: str,
    auth: HTTPBasicAuth,
    jql: str
) -> List[Dict[str, Any]]:
    """
    Fetch issues using a custom JQL query with startAt pagination.
    """
    all_issues = []
    start_at = 0
    max_results = ISSUE_PAGE_SIZE

    print(f"   Using JQL: {jql}")
    sys.stdout.flush()

    while True:
        url = f"{base_url}/rest/api/3/search/jql"
        params = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": max_results,
            "fields": "key,id"
        }

        try:
            response = requests.get(url, auth=auth, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            issues = data.get("issues", [])
            total = data.get("total", 0)
            all_issues.extend(issues)

            # Check if we've retrieved all issues
            if start_at + len(issues) >= total or not issues:
                break

            # Update startAt for next page
            start_at += len(issues)

            # Small delay to avoid rate limiting
            time.sleep(0.1)

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:  # Rate limit
                retry_after = int(e.response.headers.get('Retry-After', 10))
                print(f"      Rate limited. Waiting {retry_after} seconds...")
                sys.stdout.flush()
                time.sleep(retry_after)
                continue
            else:
                print(f"      Error fetching issues: {e}")
                sys.stdout.flush()
                break
        except Exception as e:
            print(f"      Error fetching issues: {e}")
            sys.stdout.flush()
            break

    print(f"   Found {len(all_issues)} issues matching filters")
    sys.stdout.flush()
    return all_issues


def fetch_worklogs_with_filters(
    base_url: str,
    auth: HTTPBasicAuth,
    start_date: str = None,
    end_date: str = None,
    issue_key: str = None,
    issue_id: str = None,
    author_id: str = None,
    worklog_ids: List[int] = None,
    max_workers: int = MAX_WORKERS
) -> List[Dict[str, Any]]:
    """
    Fetch worklogs with flexible filtering options.
    All parameters are optional and can be combined.

    Priority order:
    1. worklog_ids - fetch specific worklogs directly
    2. issue_key - fetch worklogs for specific issue
    3. issue_id - fetch worklogs for specific issue ID
    4. author_id + date range - use JQL to find issues then fetch worklogs
    5. date range only - use existing date range logic
    """
    all_worklogs = []

    # Priority 1: Specific worklog IDs
    if worklog_ids:
        print(f"\n   Filter Mode: SPECIFIC WORKLOG IDs ({len(worklog_ids)} IDs)")
        sys.stdout.flush()
        return fetch_worklogs_by_ids_parallel(base_url, auth, worklog_ids, max_workers)

    # Priority 2: Specific issue key
    if issue_key:
        print(f"\n   Filter Mode: ISSUE KEY ({issue_key})")
        sys.stdout.flush()
        worklogs = fetch_worklogs_for_single_issue_key(
            base_url, auth, issue_key, start_date, end_date
        )
        return worklogs

    # Priority 3: Specific issue ID
    if issue_id:
        print(f"\n   Filter Mode: ISSUE ID ({issue_id})")
        sys.stdout.flush()
        worklogs = fetch_worklogs_for_issue_id(
            base_url, auth, issue_id, start_date, end_date
        )
        return worklogs

    # Priority 4: Author ID filter (with or without date range)
    if author_id:
        print(f"\n   Filter Mode: AUTHOR ID ({author_id})")
        if start_date:
            print(f"   Date range: {start_date} to {end_date or 'now'}")
        sys.stdout.flush()

        jql = build_jql_with_filters(
            start_date=start_date,
            end_date=end_date,
            author_id=author_id
        )

        issues = fetch_issues_with_filters(base_url, auth, jql)

        if issues:
            # Fetch worklogs for all matching issues
            all_worklogs = fetch_worklogs_for_issues_parallel(
                base_url, auth, issues, max_workers, show_progress=True
            )

            # Filter worklogs by author_id (since JQL only filters issues with worklogs by author)
            filtered_worklogs = [
                w for w in all_worklogs
                if w.get('author_id') == author_id
            ]

            # Also filter by date if specified
            if start_date or end_date:
                def in_date_range(worklog):
                    started = worklog.get('started', '')
                    started_date = started.split('T')[0] if started else ''
                    if start_date and started_date < start_date:
                        return False
                    if end_date and started_date >= end_date:
                        return False
                    return True

                filtered_worklogs = [w for w in filtered_worklogs if in_date_range(w)]

            print(f"   Filtered to {len(filtered_worklogs)} worklogs by author {author_id}")
            sys.stdout.flush()
            return filtered_worklogs

        return []

    # Priority 5: Date range only - use existing chunked approach
    # This will be handled by the main run_pipeline logic
    return None  # Signal to use existing date range logic


def run_pipeline(
    mode: str = "initial",
    max_workers: int = MAX_WORKERS,
    start_date: str = None,
    end_date: str = None,
    issue_key: str = None,
    issue_id: str = None,
    author_id: str = None,
    worklog_ids: List[int] = None
):
    """
    Run the OPTIMIZED Jira worklogs pipeline.

    Args:
        mode: 'initial' for full extract, 'daily' for incremental
        max_workers: Number of parallel workers for issue processing
        start_date: Start date (YYYY-MM-DD). If None, uses JIRA_START_DATE env var
        end_date: End date (YYYY-MM-DD). If None, uses today's date
        issue_key: Optional issue key to filter (e.g., "PROJ-123")
        issue_id: Optional issue ID to filter
        author_id: Optional author account ID to filter
        worklog_ids: Optional list of specific worklog IDs to fetch
    """
    # Determine if we're in filter mode (any specific filter provided)
    filter_mode = any([issue_key, issue_id, author_id, worklog_ids])
    # Determine if we're in parametric mode (explicit dates provided)
    parametric_mode = start_date is not None or end_date is not None

    print("=" * 80)
    print(f"Jira Worklogs Pipeline (OPTIMIZED) - Mode: {mode.upper()}")
    if filter_mode:
        print("   *** FILTER MODE - Using specific filters ***")
    elif parametric_mode:
        print("   *** PARAMETRIC MODE - Using provided date range ***")
    print("=" * 80)
    print(f"   Max workers (issues): {max_workers}")
    print(f"   Date range workers: {DATE_RANGE_WORKERS}")
    print(f"   Request timeout: {REQUEST_TIMEOUT}s")
    print(f"   Max retries: {MAX_RETRIES}")
    print(f"   Batch size: {BATCH_SIZE}")
    print(f"   Issues per chunk: {ISSUES_PER_CHUNK}")
    print(f"   Days per chunk: {DAYS_PER_CHUNK}")

    # Print filter parameters if any
    if filter_mode:
        print("-" * 40)
        print("   Active Filters:")
        if issue_key:
            print(f"      Issue Key: {issue_key}")
        if issue_id:
            print(f"      Issue ID: {issue_id}")
        if author_id:
            print(f"      Author ID: {author_id}")
        if worklog_ids:
            print(f"      Worklog IDs: {worklog_ids[:5]}{'...' if len(worklog_ids) > 5 else ''}")
        if start_date:
            print(f"      Start Date: {start_date}")
        if end_date:
            print(f"      End Date: {end_date}")
        print("-" * 40)

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
        raise ValueError("Missing required environment variables: JIRA_SUBDOMAIN, JIRA_EMAIL, JIRA_API_TOKEN")

    auth = HTTPBasicAuth(email, api_token)

    print("\nExtracting Data...")
    sys.stdout.flush()

    # Handle filter mode - when specific filters are provided
    if filter_mode:
        print("\n   Using FILTER MODE - fetching specific worklogs...")
        sys.stdout.flush()

        # Use the unified filter function
        filtered_worklogs = fetch_worklogs_with_filters(
            base_url=base_url,
            auth=auth,
            start_date=start_date,
            end_date=end_date,
            issue_key=issue_key,
            issue_id=issue_id,
            author_id=author_id,
            worklog_ids=worklog_ids,
            max_workers=max_workers
        )

        if filtered_worklogs is None:
            # This means no specific filter was matched, fall through to date range
            filter_mode = False
        else:
            # We have filtered worklogs, load them
            if not filtered_worklogs:
                print("   No worklogs found matching filters")
                sys.stdout.flush()
            else:
                print(f"\n   Found {len(filtered_worklogs)} worklogs matching filters")
                sys.stdout.flush()

            # Create pipeline
            pipeline = dlt.pipeline(
                pipeline_name=PIPELINE_NAME,
                destination="postgres",
                dataset_name=SCHEMA_NAME
            )

            # Sync state with database
            sync_dlt_state_with_database(pipeline, SCHEMA_NAME, TABLE_NAME)

            # Recreate pipeline after state sync
            pipeline = dlt.pipeline(
                pipeline_name=PIPELINE_NAME,
                destination="postgres",
                dataset_name=SCHEMA_NAME
            )

            # Always use merge for filter mode to preserve existing data
            print(f"\n   Loading {len(filtered_worklogs)} worklogs to database (merge mode)...")
            sys.stdout.flush()

            if filtered_worklogs:
                load_info = pipeline.run(
                    dlt.resource(filtered_worklogs, name=TABLE_NAME, write_disposition="merge", primary_key="id")
                )

                if load_info.has_failed_jobs:
                    raise Exception("DLT load failed with failed jobs")
            else:
                load_info = None

            print("\n" + "=" * 80)
            print("Jira Worklogs Load Completed (FILTER MODE)!")
            print("=" * 80)
            print(f"   Pipeline: {PIPELINE_NAME}")
            print(f"   Dataset: {SCHEMA_NAME}")
            print(f"   Table: {SCHEMA_NAME}.{TABLE_NAME}")
            print(f"   Worklogs loaded: {len(filtered_worklogs)}")
            if issue_key:
                print(f"   Filter: issue_key={issue_key}")
            if issue_id:
                print(f"   Filter: issue_id={issue_id}")
            if author_id:
                print(f"   Filter: author_id={author_id}")
            if worklog_ids:
                print(f"   Filter: {len(worklog_ids)} worklog IDs")
            print("=" * 80)
            sys.stdout.flush()

            return load_info

    if mode == "initial":
        # Use provided dates if available, otherwise fall back to env vars
        if start_date:
            extract_start = start_date
            print(f"Mode: INITIAL - Using provided start_date: {extract_start}")
        else:
            jira_start_date = os.getenv("JIRA_START_DATE", "2024-01-01T00:00:00Z")
            extract_start = jira_start_date.split('T')[0]
            print(f"Mode: INITIAL - Using env JIRA_START_DATE: {extract_start}")

        if end_date:
            extract_end = end_date
            print(f"   Using provided end_date: {extract_end}")
        else:
            extract_end = datetime.now().strftime('%Y-%m-%d')
            print(f"   Using default end_date (today): {extract_end}")

        print(f"Using {DAYS_PER_CHUNK}-day chunks with parallel processing...")
        print(f"Date range parallelization: {DATE_RANGE_WORKERS} workers")
        sys.stdout.flush()

        # Generate date ranges
        date_ranges = generate_date_ranges(extract_start, extract_end, days_per_chunk=DAYS_PER_CHUNK)

        total_ranges = len(date_ranges)
        total_worklogs_loaded = 0

        print(f"\n   Extracting worklogs in {total_ranges} chunks ({DAYS_PER_CHUNK}-day each)...")
        print(f"   Date range: {extract_start} to {extract_end}")
        print()
        sys.stdout.flush()

        # Process date ranges sequentially to maintain database commit order
        # (but each date range uses parallel processing internally)
        for range_idx, (range_start, range_end) in enumerate(date_ranges):
            chunk_num = range_idx + 1
            is_first_chunk = (range_idx == 0)

            print(f"   Chunk {chunk_num}/{total_ranges}: {range_start} to {range_end}")
            sys.stdout.flush()

            # Extract worklogs for this date range (uses parallel processing internally)
            worklogs = extract_worklogs_for_date_range(
                base_url, auth, range_start, range_end, max_workers
            )

            if not worklogs:
                print(f"      No worklogs found in this range")
                print()
                sys.stdout.flush()
                continue

            # Create pipeline for this chunk
            pipeline = dlt.pipeline(
                pipeline_name=PIPELINE_NAME,
                destination="postgres",
                dataset_name=SCHEMA_NAME
            )

            # In parametric mode: always use merge to preserve existing data
            # In normal mode: first chunk uses replace, subsequent use merge
            if parametric_mode:
                # Parametric mode: always merge to add to existing data
                if is_first_chunk:
                    sync_dlt_state_with_database(pipeline, SCHEMA_NAME, TABLE_NAME)
                    pipeline = dlt.pipeline(
                        pipeline_name=PIPELINE_NAME,
                        destination="postgres",
                        dataset_name=SCHEMA_NAME
                    )
                write_disposition = "merge"
            else:
                # Normal mode: first chunk replaces, subsequent merge
                if is_first_chunk:
                    sync_dlt_state_with_database(pipeline, SCHEMA_NAME, TABLE_NAME)
                    pipeline = dlt.pipeline(
                        pipeline_name=PIPELINE_NAME,
                        destination="postgres",
                        dataset_name=SCHEMA_NAME
                    )
                    write_disposition = "replace"
                else:
                    write_disposition = "merge"

            # Load this chunk's worklogs to database
            print(f"      Loading {len(worklogs)} worklogs to database ({write_disposition} mode)...")
            sys.stdout.flush()

            load_info = pipeline.run(
                dlt.resource(worklogs, name=TABLE_NAME, write_disposition=write_disposition, primary_key="id")
            )

            if load_info.has_failed_jobs:
                print(f"      ERROR: Failed to load chunk {chunk_num}")
                sys.stdout.flush()
                raise Exception(f"DLT load failed for chunk {chunk_num}")

            total_worklogs_loaded += len(worklogs)
            print(f"      Chunk {chunk_num} committed: {len(worklogs)} worklogs (total: {total_worklogs_loaded})")
            print()
            sys.stdout.flush()

        print(f"\n   Extraction complete!")
        print(f"   Total worklogs loaded: {total_worklogs_loaded}")
        sys.stdout.flush()

        # Create final load_info for return
        pipeline = dlt.pipeline(
            pipeline_name=PIPELINE_NAME,
            destination="postgres",
            dataset_name=SCHEMA_NAME
        )
        load_info = pipeline.last_trace

    else:  # daily mode
        lookback_days = int(os.getenv("JIRA_INCREMENTAL_DAYS", "30"))
        print(f"Mode: DAILY - Lookback {lookback_days} days")
        print(f"Using parallel batch processing with {max_workers} workers...")
        sys.stdout.flush()

        since_timestamp = int((datetime.now() - timedelta(days=lookback_days)).timestamp() * 1000)

        # Use bulk API for daily
        print("\n   Step 1: Getting updated worklog IDs (bulk API)...")
        sys.stdout.flush()
        worklog_ids = get_worklog_ids_updated_since(base_url, auth, since_timestamp)

        if worklog_ids:
            print(f"   Found {len(worklog_ids)} updated worklogs")
            print("\n   Step 2: Fetching worklog details in parallel batches...")
            sys.stdout.flush()
            all_worklogs = fetch_worklogs_by_ids_parallel(base_url, auth, worklog_ids, max_workers)
        else:
            print("   No updated worklogs found")
            sys.stdout.flush()
            all_worklogs = []

        print(f"\nTotal worklogs: {len(all_worklogs)}")
        sys.stdout.flush()

        # Create pipeline
        pipeline = dlt.pipeline(
            pipeline_name=PIPELINE_NAME,
            destination="postgres",
            dataset_name=SCHEMA_NAME
        )

        # Sync state with database
        sync_dlt_state_with_database(pipeline, SCHEMA_NAME, TABLE_NAME)

        # Recreate pipeline after state sync
        pipeline = dlt.pipeline(
            pipeline_name=PIPELINE_NAME,
            destination="postgres",
            dataset_name=SCHEMA_NAME
        )

        print(f"\nLoading to Database (merge mode)...")
        sys.stdout.flush()

        load_info = pipeline.run(
            dlt.resource(all_worklogs, name=TABLE_NAME, write_disposition="merge", primary_key="id")
        )

        if load_info.has_failed_jobs:
            raise Exception("DLT load failed with failed jobs")

    print("\n" + "=" * 80)
    print("Jira Worklogs Load Completed (OPTIMIZED)!")
    print("=" * 80)
    print(f"   Pipeline: {PIPELINE_NAME}")
    print(f"   Dataset: {SCHEMA_NAME}")
    print(f"   Table: {SCHEMA_NAME}.{TABLE_NAME}")
    print(f"   Mode: {mode}")
    print(f"   Max workers used: {max_workers}")
    print("=" * 80)
    sys.stdout.flush()

    return load_info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jira Worklogs DLT Pipeline (OPTIMIZED)")
    parser.add_argument("--mode", choices=["initial", "daily"], default="initial",
                        help="Pipeline mode: initial (full extract) or daily (incremental)")
    parser.add_argument("--max-workers", type=int, default=MAX_WORKERS,
                        help=f"Maximum parallel workers for issue processing (default: {MAX_WORKERS})")
    parser.add_argument("--start-date", type=str, default=None,
                        help="Start date for extraction (YYYY-MM-DD). Overrides JIRA_START_DATE env var.")
    parser.add_argument("--end-date", type=str, default=None,
                        help="End date for extraction (YYYY-MM-DD). Overrides default (today).")
    parser.add_argument("--issue-key", type=str, default=None,
                        help="Filter by specific issue key (e.g., PROJ-123)")
    parser.add_argument("--issue-id", type=str, default=None,
                        help="Filter by specific issue ID")
    parser.add_argument("--author-id", type=str, default=None,
                        help="Filter by author account ID")
    parser.add_argument("--worklog-id", type=str, default=None,
                        help="Fetch specific worklog ID(s), comma-separated (e.g., 10000,10001,10002)")
    args = parser.parse_args()

    # Parse worklog IDs if provided
    worklog_ids = None
    if args.worklog_id:
        try:
            worklog_ids = [int(x.strip()) for x in args.worklog_id.split(",")]
        except ValueError:
            print(f"Error: Invalid worklog IDs format. Expected comma-separated integers.")
            sys.exit(1)

    run_pipeline(
        mode=args.mode,
        max_workers=args.max_workers,
        start_date=args.start_date,
        end_date=args.end_date,
        issue_key=args.issue_key,
        issue_id=args.issue_id,
        author_id=args.author_id,
        worklog_ids=worklog_ids
    )
