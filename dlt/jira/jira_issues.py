"""
Jira Issues DLT Pipeline

Extracts Jira issues and loads them to PostgreSQL.

Pipeline Modes:
    - initial: Full replace using parallel extraction (all issues from JIRA_START_DATE)
    - daily: Merge mode - updates only issues modified in last N days

Filtering Options (all optional, can be combined):
    - start_date/end_date: Date range filter (YYYY-MM-DD)
    - issue_key: Filter by specific issue key (e.g., "PROJ-123")
    - issue_id: Filter by specific issue ID
    - issue_type: Filter by issue type name (e.g., "Bug", "Story", "Task")

Usage:
    # From command line (default: initial mode)
    docker exec ppm-dlt python /app/jira/jira_issues.py

    # With specific mode
    docker exec ppm-dlt python /app/jira/jira_issues.py --mode=daily
    docker exec ppm-dlt python /app/jira/jira_issues.py --mode=initial

    # With optional filters:
    docker exec ppm-dlt python /app/jira/jira_issues.py --issue-key=PROJ-123
    docker exec ppm-dlt python /app/jira/jira_issues.py --issue-type=Bug --start-date=2024-01-01
    docker exec ppm-dlt python /app/jira/jira_issues.py --issue-id=10001

    # From Mage (via dlt_runner utility)
    from utils.dlt_runner import run_dlt_script
    result = run_dlt_script(
        script_path='/home/dlt/jira/jira_issues.py',
        target_table='raw_jira.issues',
        extra_args=['--mode=daily']
    )

Features:
    - Schema evolution: Creates table if not exists
    - Parallel extraction for initial load (4 workers)
    - Incremental updates for daily load (merge mode)
    - Optional filtering by issue_key, issue_id, or issue_type
"""

import dlt
from dlt.common.schema.typing import TWriteDisposition
import requests
from requests.auth import HTTPBasicAuth
import os
import sys
import argparse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any
import time
import json

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dlt_utils import (
    table_exists,
    sync_dlt_state_with_database,
    determine_write_disposition
)

# ===== CONFIGURATION =====
TABLE_NAME = "issues"
SCHEMA_NAME = "raw_jira"
PIPELINE_NAME = "jira_issues"

# Parallel extraction settings
MAX_WORKERS = 4
MAX_RETRIES = 3
RETRY_DELAY = 2
ISSUES_PER_PAGE = 100

# Standard Jira fields to extract
SELECTED_STANDARD_FIELDS = [
    "key", "summary", "status", "created", "updated",
    "assignee", "reporter", "creator", "priority", "issuetype",
    "project", "description", "labels", "components",
    "fixVersions", "duedate", "resolutiondate", "resolution",
    "timetracking", "timespent", "timeoriginalestimate",
    "parent"
]


def generate_monthly_date_ranges(start_date: str, end_date: str = None) -> List[tuple]:
    """Generate monthly date ranges from start_date to end_date"""
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
    """Fetch issues for a specific date range"""
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
                response = requests.get(url, auth=auth, params=params)
                response.raise_for_status()
                data = response.json()
                issues = data.get("issues", [])
                all_issues.extend(issues)

                next_page_token = data.get("nextPageToken")
                if not next_page_token or not issues:
                    print(f"   [{range_idx + 1}/{total_ranges}] {start_date} to {end_date}: {len(all_issues)} issues")
                    return all_issues

                break

            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                else:
                    print(f"   [{range_idx + 1}/{total_ranges}] Failed: {e}")
                    return all_issues

    return all_issues


def fetch_all_issues_parallel(
    base_url: str,
    auth: HTTPBasicAuth,
    jira_start_date: str,
    jira_end_date: str = None
) -> List[Dict[str, Any]]:
    """Fetch ALL issues using parallel extraction by date ranges (for initial load)"""
    jql_start_date = jira_start_date.split('T')[0]
    jql_end_date = jira_end_date.split('T')[0] if jira_end_date else None

    print(f"   Fetching issues from Jira...")
    print(f"   Date range: {jql_start_date} to {jql_end_date or 'today'}")
    print(f"   Strategy: Parallel extraction with {MAX_WORKERS} workers")

    date_ranges = generate_monthly_date_ranges(jql_start_date, jql_end_date)
    total_ranges = len(date_ranges)
    print(f"   Generated {total_ranges} monthly date ranges")

    all_issues = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_range = {
            executor.submit(
                fetch_issues_for_date_range, base_url, auth, start, end,
                SELECTED_STANDARD_FIELDS, idx, total_ranges
            ): (start, end, idx)
            for idx, (start, end) in enumerate(date_ranges)
        }

        for future in as_completed(future_to_range):
            try:
                issues = future.result()
                all_issues.extend(issues)
            except Exception as e:
                print(f"   Exception: {e}")

    print(f"   Completed: Fetched {len(all_issues)} total issues")
    return all_issues


def fetch_updated_issues(base_url: str, auth: HTTPBasicAuth, lookback_days: int) -> List[Dict[str, Any]]:
    """Fetch issues updated in the last N days (for daily load)"""
    lookback_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    jql = f"updated >= '{lookback_date}' ORDER BY updated DESC"

    print(f"   Fetching issues updated since {lookback_date}...")

    all_issues = []
    next_page_token = None

    while True:
        url = f"{base_url}/rest/api/3/search/jql"
        params = {
            "jql": jql,
            "maxResults": ISSUES_PER_PAGE,
            "fields": ",".join(SELECTED_STANDARD_FIELDS)
        }

        if next_page_token:
            params["nextPageToken"] = next_page_token

        try:
            response = requests.get(url, auth=auth, params=params)
            response.raise_for_status()
            data = response.json()
            issues = data.get("issues", [])
            all_issues.extend(issues)

            total = data.get("total", len(all_issues))
            print(f"   Retrieved {len(all_issues)}/{total} updated issues")

            next_page_token = data.get("nextPageToken")
            if not next_page_token or not issues:
                break

        except Exception as e:
            print(f"   Error: {e}")
            raise

    return all_issues


def flatten_issue(issue: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten issue to reduce nesting"""
    fields = issue.get('fields', {})

    def safe_get(obj, *keys):
        for key in keys:
            if obj is None:
                return None
            if isinstance(obj, dict):
                obj = obj.get(key)
            else:
                return None
        return obj

    # Serialize description as JSON to prevent DLT from creating nested tables
    description = fields.get('description')
    if description is not None:
        description = json.dumps(description)

    # Serialize labels as JSON to prevent DLT from creating nested tables
    labels = fields.get('labels')
    if labels is not None:
        labels = json.dumps(labels)

    return {
        'id': issue.get('id'),
        'key': issue.get('key'),
        'summary': fields.get('summary'),
        'created': fields.get('created'),
        'updated': fields.get('updated'),
        'status_name': safe_get(fields, 'status', 'name'),
        'status_category': safe_get(fields, 'status', 'statusCategory', 'name'),
        'assignee_id': safe_get(fields, 'assignee', 'accountId'),
        'assignee_name': safe_get(fields, 'assignee', 'displayName'),
        'reporter_id': safe_get(fields, 'reporter', 'accountId'),
        'reporter_name': safe_get(fields, 'reporter', 'displayName'),
        'creator_id': safe_get(fields, 'creator', 'accountId'),
        'creator_name': safe_get(fields, 'creator', 'displayName'),
        'issuetype_name': safe_get(fields, 'issuetype', 'name'),
        'priority_name': safe_get(fields, 'priority', 'name'),
        'project_id': safe_get(fields, 'project', 'id'),
        'project_key': safe_get(fields, 'project', 'key'),
        'project_name': safe_get(fields, 'project', 'name'),
        'parent_id': safe_get(fields, 'parent', 'id'),
        'parent_key': safe_get(fields, 'parent', 'key'),
        'is_subtask': safe_get(fields, 'issuetype', 'subtask') or False,
        'description': description,
        'labels': labels,
        'resolution': safe_get(fields, 'resolution', 'name'),
        'resolutiondate': fields.get('resolutiondate'),
        'duedate': fields.get('duedate'),
        'timespent': fields.get('timespent'),
        'timeoriginalestimate': fields.get('timeoriginalestimate'),
        '_etl_date': datetime.now().isoformat(),
    }


def fetch_issue_by_key(
    base_url: str,
    auth: HTTPBasicAuth,
    issue_key: str
) -> List[Dict[str, Any]]:
    """
    Fetch a specific issue by its key.
    """
    print(f"   Fetching issue by key: {issue_key}")

    url = f"{base_url}/rest/api/3/issue/{issue_key}"
    params = {"fields": ",".join(SELECTED_STANDARD_FIELDS)}

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, auth=auth, params=params)
            response.raise_for_status()
            issue = response.json()
            print(f"   Found issue: {issue_key}")
            return [issue]

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                print(f"   Issue {issue_key} not found")
                return []
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                print(f"   Error fetching issue {issue_key}: {e}")
                raise
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                print(f"   Error fetching issue {issue_key}: {e}")
                raise

    return []


def fetch_issue_by_id(
    base_url: str,
    auth: HTTPBasicAuth,
    issue_id: str
) -> List[Dict[str, Any]]:
    """
    Fetch a specific issue by its ID.
    """
    print(f"   Fetching issue by ID: {issue_id}")

    url = f"{base_url}/rest/api/3/issue/{issue_id}"
    params = {"fields": ",".join(SELECTED_STANDARD_FIELDS)}

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, auth=auth, params=params)
            response.raise_for_status()
            issue = response.json()
            print(f"   Found issue ID {issue_id}: {issue.get('key')}")
            return [issue]

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                print(f"   Issue ID {issue_id} not found")
                return []
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                print(f"   Error fetching issue ID {issue_id}: {e}")
                raise
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                print(f"   Error fetching issue ID {issue_id}: {e}")
                raise

    return []


def build_jql_with_filters(
    start_date: str = None,
    end_date: str = None,
    issue_type: str = None
) -> str:
    """
    Build JQL query dynamically based on provided filters.
    All filters are optional and can be combined.
    """
    conditions = []

    # Date range filter
    if start_date and end_date:
        conditions.append(f"created >= '{start_date}' AND created <= '{end_date}'")
    elif start_date:
        conditions.append(f"created >= '{start_date}'")
    elif end_date:
        conditions.append(f"created <= '{end_date}'")

    # Issue type filter
    if issue_type:
        conditions.append(f'issuetype = "{issue_type}"')

    if not conditions:
        return "ORDER BY created ASC"

    jql = " AND ".join(conditions) + " ORDER BY created ASC"
    return jql


def fetch_issues_with_filters(
    base_url: str,
    auth: HTTPBasicAuth,
    jql: str
) -> List[Dict[str, Any]]:
    """
    Fetch issues using a custom JQL query.
    """
    all_issues = []
    next_page_token = None

    print(f"   Using JQL: {jql}")

    while True:
        url = f"{base_url}/rest/api/3/search/jql"
        params = {
            "jql": jql,
            "maxResults": ISSUES_PER_PAGE,
            "fields": ",".join(SELECTED_STANDARD_FIELDS)
        }

        if next_page_token:
            params["nextPageToken"] = next_page_token

        try:
            response = requests.get(url, auth=auth, params=params)
            response.raise_for_status()
            data = response.json()
            issues = data.get("issues", [])
            all_issues.extend(issues)

            total = data.get("total", len(all_issues))
            print(f"   Retrieved {len(all_issues)}/{total} issues")

            next_page_token = data.get("nextPageToken")
            if not next_page_token or not issues:
                break

        except Exception as e:
            print(f"   Error fetching issues: {e}")
            raise

    print(f"   Found {len(all_issues)} issues matching filters")
    return all_issues


def fetch_issues_by_type(
    base_url: str,
    auth: HTTPBasicAuth,
    issue_type: str,
    start_date: str = None,
    end_date: str = None
) -> List[Dict[str, Any]]:
    """
    Fetch issues filtered by issue type, optionally with date range.
    """
    print(f"   Fetching issues by type: {issue_type}")
    if start_date:
        print(f"   Date range: {start_date} to {end_date or 'now'}")

    jql = build_jql_with_filters(
        start_date=start_date,
        end_date=end_date,
        issue_type=issue_type
    )

    return fetch_issues_with_filters(base_url, auth, jql)


def get_missing_issues_from_database() -> List[str]:
    """Query database to find all missing issue keys from worklogs, subtasks, and links"""
    import psycopg2

    db_host = os.getenv("POSTGRES_HOST", "postgres")
    db_port = int(os.getenv("POSTGRES_PORT", "5432"))
    db_name = os.getenv("POSTGRES_DB", "ppm_datawarehouse")
    db_user = os.getenv("POSTGRES_USER", "ppm_user")
    db_password = os.getenv("POSTGRES_PASSWORD", "")

    conn = psycopg2.connect(
        host=db_host, port=db_port, database=db_name,
        user=db_user, password=db_password
    )
    cursor = conn.cursor()

    query = """
    WITH worklog_keys AS (
      SELECT DISTINCT w.issue_key AS key
      FROM raw_jira.worklogs w
      LEFT JOIN raw_jira.issues i ON w.issue_key = i.key
      WHERE w.issue_key IS NOT NULL AND i.key IS NULL
    ),
    subtask_parent_keys AS (
      SELECT DISTINCT s.parent_key AS key
      FROM raw_jira.issue_subtasks s
      LEFT JOIN raw_jira.issues i ON s.parent_key = i.key
      WHERE s.parent_key IS NOT NULL AND i.key IS NULL
    ),
    subtask_child_keys AS (
      SELECT DISTINCT s.subtask_key AS key
      FROM raw_jira.issue_subtasks s
      LEFT JOIN raw_jira.issues i ON s.subtask_key = i.key
      WHERE s.subtask_key IS NOT NULL AND i.key IS NULL
    ),
    link_source_keys AS (
      SELECT DISTINCT l.source_issue_key AS key
      FROM raw_jira.issue_links l
      LEFT JOIN raw_jira.issues i ON l.source_issue_key = i.key
      WHERE l.source_issue_key IS NOT NULL AND i.key IS NULL
    ),
    link_target_keys AS (
      SELECT DISTINCT l.target_issue_key AS key
      FROM raw_jira.issue_links l
      LEFT JOIN raw_jira.issues i ON l.target_issue_key = i.key
      WHERE l.target_issue_key IS NOT NULL AND i.key IS NULL
    )
    SELECT key FROM worklog_keys
    UNION
    SELECT key FROM subtask_parent_keys
    UNION
    SELECT key FROM subtask_child_keys
    UNION
    SELECT key FROM link_source_keys
    UNION
    SELECT key FROM link_target_keys
    ORDER BY key;
    """

    cursor.execute(query)
    missing_keys = [row[0] for row in cursor.fetchall()]

    cursor.close()
    conn.close()

    print(f"   Identified {len(missing_keys)} unique missing issue keys from database")

    return missing_keys


def fetch_issues_by_keys_bulk(
    base_url: str,
    auth: HTTPBasicAuth,
    issue_keys: List[str]
) -> List[Dict[str, Any]]:
    """Fetch multiple issues by their keys using individual API calls"""
    print(f"   Fetching {len(issue_keys)} issues by keys...")

    fetched_issues = []
    not_found_keys = []

    for idx, issue_key in enumerate(issue_keys, 1):
        if idx % 25 == 0:
            print(f"   Progress: {idx}/{len(issue_keys)} ({len(fetched_issues)} found, {len(not_found_keys)} not found)")

        url = f"{base_url}/rest/api/3/issue/{issue_key}"
        params = {"fields": ",".join(SELECTED_STANDARD_FIELDS)}

        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(url, auth=auth, params=params, timeout=30)

                if response.status_code == 404:
                    not_found_keys.append(issue_key)
                    break

                response.raise_for_status()
                issue = response.json()
                fetched_issues.append(issue)
                break

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    not_found_keys.append(issue_key)
                    break
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                else:
                    print(f"   Error fetching {issue_key}: {e}")
                    not_found_keys.append(issue_key)
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                else:
                    print(f"   Error fetching {issue_key}: {e}")
                    not_found_keys.append(issue_key)

        # Rate limiting
        time.sleep(0.05)

    print(f"\n   Fetch complete:")
    print(f"      Found: {len(fetched_issues)} issues")
    print(f"      Not found (deleted/no access): {len(not_found_keys)} issues")
    if not_found_keys:
        print(f"      Sample not found: {not_found_keys[:10]}")

    return fetched_issues


def run_pipeline(
    mode: str = "initial",
    start_date: str = None,
    end_date: str = None,
    issue_key: str = None,
    issue_id: str = None,
    issue_type: str = None,
    fetch_missing: bool = False
):
    """
    Run the Jira issues pipeline.

    Args:
        mode: 'initial' for full replace, 'daily' for merge/upsert
        start_date: Start date (YYYY-MM-DD). If None, uses JIRA_START_DATE env var
        end_date: End date (YYYY-MM-DD). If None, uses today's date
        issue_key: Optional issue key to filter (e.g., "PROJ-123")
        issue_id: Optional issue ID to filter
        issue_type: Optional issue type to filter (e.g., "Bug", "Story", "Task")
        fetch_missing: If True, fetch missing issues from database relationships
    """
    # Determine if we're in filter mode (any specific filter provided)
    filter_mode = any([issue_key, issue_id, issue_type])
    # Determine if we're in parametric mode (explicit dates provided)
    parametric_mode = start_date is not None or end_date is not None

    print("=" * 80)
    print(f"Jira Issues Pipeline - Mode: {mode.upper()}")
    if filter_mode:
        print("   *** FILTER MODE - Using specific filters ***")
    elif parametric_mode:
        print("   *** PARAMETRIC MODE - Using provided date range ***")

    # Print filter parameters if any
    if filter_mode:
        print("-" * 40)
        print("   Active Filters:")
        if issue_key:
            print(f"      Issue Key: {issue_key}")
        if issue_id:
            print(f"      Issue ID: {issue_id}")
        if issue_type:
            print(f"      Issue Type: {issue_type}")
        if start_date:
            print(f"      Start Date: {start_date}")
        if end_date:
            print(f"      End Date: {end_date}")
        print("-" * 40)

    print("=" * 80)

    # Get credentials
    base_url = os.getenv("JIRA_SUBDOMAIN", "").strip('"')
    email = os.getenv("JIRA_EMAIL", "").strip('"')
    api_token = os.getenv("JIRA_API_TOKEN", "").strip('"')

    # Also check DLT source config format
    if not base_url:
        base_url = os.getenv("SOURCES__JIRA__SUBDOMAIN", "").strip('"')
    if not email:
        email = os.getenv("SOURCES__JIRA__EMAIL", "").strip('"')
    if not api_token:
        api_token = os.getenv("SOURCES__JIRA__API_TOKEN", "").strip('"')

    if not all([base_url, email, api_token]):
        raise ValueError("Missing required environment variables: JIRA_SUBDOMAIN, JIRA_EMAIL, JIRA_API_TOKEN")

    auth = HTTPBasicAuth(email, api_token)

    # Handle fetch_missing mode - fetch issues missing from database relationships
    if fetch_missing:
        print("\n" + "=" * 80)
        print("FETCH MISSING MODE - Fetching issues from database relationships")
        print("=" * 80)

        # Get missing issue keys from database
        print("\nStep 1: Querying database for missing issues...")
        missing_keys = get_missing_issues_from_database()

        if not missing_keys:
            print("   No missing issues found! All relationships are satisfied.")
            print("=" * 80)
            return None

        print(f"   Found {len(missing_keys)} missing issue keys")
        print(f"   Sample: {missing_keys[:10]}")

        # Fetch missing issues
        print(f"\nStep 2: Fetching {len(missing_keys)} missing issues from Jira...")
        raw_issues = fetch_issues_by_keys_bulk(base_url, auth, missing_keys)

        if not raw_issues:
            print("\n   No issues could be fetched (all deleted or no access)")
            print("=" * 80)
            return None

        # Process issues
        print(f"\nStep 3: Processing {len(raw_issues)} issues...")
        flattened_issues = [flatten_issue(issue) for issue in raw_issues]

        # Create pipeline
        pipeline = dlt.pipeline(
            pipeline_name=PIPELINE_NAME,
            destination="postgres",
            dataset_name=SCHEMA_NAME
        )

        # Sync state
        sync_dlt_state_with_database(pipeline, SCHEMA_NAME, TABLE_NAME)

        # Recreate pipeline
        pipeline = dlt.pipeline(
            pipeline_name=PIPELINE_NAME,
            destination="postgres",
            dataset_name=SCHEMA_NAME
        )

        # Load with merge
        print(f"\nStep 4: Loading {len(flattened_issues)} missing issues to database (merge mode)...")

        resource = dlt.resource(
            flattened_issues,
            name=TABLE_NAME,
            write_disposition="merge",
            primary_key="key",
            max_table_nesting=0,
            columns={
                "description": {"data_type": "text"},
                "labels": {"data_type": "text"}
            }
        )

        load_info = pipeline.run(resource)

        if load_info.has_failed_jobs:
            raise Exception("DLT load failed")

        print("\n" + "=" * 80)
        print("Missing Issues Fetch Completed!")
        print("=" * 80)
        print(f"   Total missing keys identified: {len(missing_keys)}")
        print(f"   Issues fetched from Jira: {len(raw_issues)}")
        print(f"   Issues loaded to database: {len(flattened_issues)}")
        print(f"   Issues not found (deleted/no access): {len(missing_keys) - len(raw_issues)}")
        print("=" * 80)

        return load_info

    # Handle filter mode - when specific filters are provided
    if filter_mode:
        print("\nUsing FILTER MODE - fetching specific issues...")

        # Fetch issues based on filter type
        raw_issues = []

        # Priority 1: Specific issue key
        if issue_key:
            print(f"\n   Filter Mode: ISSUE KEY ({issue_key})")
            raw_issues = fetch_issue_by_key(base_url, auth, issue_key)

        # Priority 2: Specific issue ID
        elif issue_id:
            print(f"\n   Filter Mode: ISSUE ID ({issue_id})")
            raw_issues = fetch_issue_by_id(base_url, auth, issue_id)

        # Priority 3: Issue type filter (with optional date range)
        elif issue_type:
            print(f"\n   Filter Mode: ISSUE TYPE ({issue_type})")
            raw_issues = fetch_issues_by_type(
                base_url, auth, issue_type, start_date, end_date
            )

        if not raw_issues:
            print("   No issues found matching filters")
        else:
            print(f"\n   Found {len(raw_issues)} issues matching filters")

        # Process issues
        print("\nProcessing issues...")
        flattened_issues = [flatten_issue(issue) for issue in raw_issues]
        print(f"Flattened {len(flattened_issues)} issues")

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
        print(f"\nLoading {len(flattened_issues)} issues to database (merge mode)...")

        if flattened_issues:
            resource = dlt.resource(
                flattened_issues,
                name=TABLE_NAME,
                write_disposition="merge",
                primary_key="key",
                max_table_nesting=0,
                columns={
                    "description": {"data_type": "text"},
                    "labels": {"data_type": "text"}
                }
            )

            load_info = pipeline.run(resource)

            if load_info.has_failed_jobs:
                raise Exception("DLT load failed with failed jobs")
        else:
            load_info = None

        print("\n" + "=" * 80)
        print("Jira Issues Load Completed (FILTER MODE)!")
        print("=" * 80)
        print(f"   Pipeline: {PIPELINE_NAME}")
        print(f"   Dataset: {SCHEMA_NAME}")
        print(f"   Table: {SCHEMA_NAME}.{TABLE_NAME}")
        print(f"   Issues loaded: {len(flattened_issues)}")
        if issue_key:
            print(f"   Filter: issue_key={issue_key}")
        if issue_id:
            print(f"   Filter: issue_id={issue_id}")
        if issue_type:
            print(f"   Filter: issue_type={issue_type}")
        print("=" * 80)

        return load_info

    # Determine write disposition based on mode
    if mode == "initial":
        # In parametric mode: use merge to preserve existing data
        # In normal mode: use replace for full refresh
        if parametric_mode:
            write_disposition: TWriteDisposition = "merge"
        else:
            write_disposition: TWriteDisposition = "replace"

        # Use provided dates if available, otherwise fall back to env vars
        if start_date:
            jira_start_date = start_date
            print(f"Mode: INITIAL - Using provided start_date: {jira_start_date}")
        else:
            jira_start_date = os.getenv("JIRA_START_DATE", "2024-01-01T00:00:00Z")
            print(f"Mode: INITIAL - Using env JIRA_START_DATE: {jira_start_date}")

        if end_date:
            jira_end_date = end_date
            print(f"   Using provided end_date: {jira_end_date}")
        else:
            jira_end_date = None  # Will use today's date
            print(f"   Using default end_date (today)")
    else:
        # Daily load: check if table exists for merge mode
        print("Mode: DAILY - Checking database state...")
        write_disposition = determine_write_disposition(SCHEMA_NAME, TABLE_NAME, default_mode="merge")
        lookback_days = int(os.getenv("JIRA_INCREMENTAL_DAYS", "60"))
        print(f"   Lookback Days: {lookback_days}")

    # Create the pipeline
    pipeline = dlt.pipeline(
        pipeline_name=PIPELINE_NAME,
        destination="postgres",
        dataset_name=SCHEMA_NAME
    )

    # Sync DLT state with database if table doesn't exist
    if write_disposition == "replace":
        sync_dlt_state_with_database(pipeline, SCHEMA_NAME, TABLE_NAME)
        # Recreate pipeline after state reset
        pipeline = dlt.pipeline(
            pipeline_name=PIPELINE_NAME,
            destination="postgres",
            dataset_name=SCHEMA_NAME
        )

    # Fetch issues based on mode
    print("\nExtracting Data...")
    if mode == "initial":
        raw_issues = fetch_all_issues_parallel(base_url, auth, jira_start_date, jira_end_date)
    else:
        raw_issues = fetch_updated_issues(base_url, auth, lookback_days)

    print(f"Fetched {len(raw_issues)} raw issues")

    # Process issues
    print("\nProcessing issues...")
    flattened_issues = [flatten_issue(issue) for issue in raw_issues]
    print(f"Flattened {len(flattened_issues)} issues")

    # Load to PostgreSQL
    print(f"\nLoading to Database ({write_disposition} mode)...")

    # Configure resource with column hints to prevent normalization
    resource = dlt.resource(
        flattened_issues,
        name=TABLE_NAME,
        write_disposition=write_disposition,
        primary_key="key",
        max_table_nesting=0,  # Prevent creation of nested tables
        columns={
            "description": {"data_type": "text"},
            "labels": {"data_type": "text"}
        }
    )

    load_info = pipeline.run(resource)

    # Verify load success
    if load_info.has_failed_jobs:
        print("\n" + "=" * 80)
        print("LOAD FAILED!")
        print("=" * 80)
        for package in load_info.load_packages:
            for job in package.jobs.get("failed_jobs", []):
                print(f"   Failed: {job.file_path}")
                if hasattr(job, 'failed_message'):
                    print(f"   Error: {job.failed_message}")
        raise Exception("DLT load failed with failed jobs")

    print("\n" + "=" * 80)
    print("Jira Issues Load Completed!")
    print("=" * 80)
    print(f"   Pipeline: {load_info.pipeline.pipeline_name}")
    print(f"   Dataset: {load_info.pipeline.dataset_name}")
    print(f"   Table: {SCHEMA_NAME}.{TABLE_NAME}")
    print(f"   Mode: {write_disposition}")
    print(f"   Records: {len(flattened_issues)} issues")
    print("=" * 80)

    return load_info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jira Issues DLT Pipeline")
    parser.add_argument(
        "--mode",
        choices=["initial", "daily"],
        default="initial",
        help="Pipeline mode: 'initial' for full replace, 'daily' for merge/upsert"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date for extraction (YYYY-MM-DD). Overrides JIRA_START_DATE env var."
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date for extraction (YYYY-MM-DD). Overrides default (today)."
    )
    parser.add_argument(
        "--issue-key",
        type=str,
        default=None,
        help="Filter by specific issue key (e.g., PROJ-123)"
    )
    parser.add_argument(
        "--issue-id",
        type=str,
        default=None,
        help="Filter by specific issue ID"
    )
    parser.add_argument(
        "--issue-type",
        type=str,
        default=None,
        help="Filter by issue type name (e.g., Bug, Story, Task)"
    )
    parser.add_argument(
        "--fetch-missing",
        action="store_true",
        default=False,
        help="Fetch missing issues from database relationships (worklogs, subtasks, links)"
    )
    args = parser.parse_args()

    run_pipeline(
        mode=args.mode,
        start_date=args.start_date,
        end_date=args.end_date,
        issue_key=args.issue_key,
        issue_id=args.issue_id,
        issue_type=args.issue_type,
        fetch_missing=args.fetch_missing
    )
