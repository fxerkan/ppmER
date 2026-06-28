"""
Jira Data Validation Script

Cross-validates data integrity between Jira tables:
- worklogs vs issues: Checks for orphaned worklogs (worklogs referencing non-existent issues)
- issues vs projects: Checks for orphaned issues (issues referencing non-existent projects)
- ID gap analysis: Identifies missing issue IDs and worklog IDs in sequences
- Author analysis: Identifies worklogs by authors with missing issues

Generates detailed reports with:
- Lists of missing issue_keys, issue_ids
- Worklog ID gaps
- Author-level breakdown
- Suggested DLT commands to fix missing data

Usage:
    docker exec ppm-dlt python /app/jira/jira_data_validation.py
    docker exec ppm-dlt python /app/jira/jira_data_validation.py --detailed
    docker exec ppm-dlt python /app/jira/jira_data_validation.py --verify-in-jira
    docker exec ppm-dlt python /app/jira/jira_data_validation.py --export-missing
"""

import os
import sys
import argparse
import psycopg2
import json
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
import requests
from requests.auth import HTTPBasicAuth
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Output file paths
MISSING_ISSUES_FILE = "/tmp/missing_issues.json"
MISSING_WORKLOGS_FILE = "/tmp/missing_worklogs.json"
FIX_COMMANDS_FILE = "/tmp/fix_commands.sh"


def get_db_connection():
    """Get database connection from environment variables"""
    host = os.getenv("DESTINATION__POSTGRES__CREDENTIALS__HOST", "postgres")
    port = os.getenv("DESTINATION__POSTGRES__CREDENTIALS__PORT", "5432")
    database = os.getenv("DESTINATION__POSTGRES__CREDENTIALS__DATABASE", "ppm_datawarehouse")
    user = os.getenv("DESTINATION__POSTGRES__CREDENTIALS__USERNAME", "ppm_user")
    password = os.getenv("DESTINATION__POSTGRES__CREDENTIALS__PASSWORD", "")

    return psycopg2.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password
    )


def get_jira_auth():
    """Get Jira authentication from environment variables"""
    base_url = os.getenv("JIRA_SUBDOMAIN", "").strip('"') or os.getenv("SOURCES__JIRA__SUBDOMAIN", "").strip('"')
    email = os.getenv("JIRA_EMAIL", "").strip('"') or os.getenv("SOURCES__JIRA__EMAIL", "").strip('"')
    api_token = os.getenv("JIRA_API_TOKEN", "").strip('"') or os.getenv("SOURCES__JIRA__API_TOKEN", "").strip('"')

    return base_url, HTTPBasicAuth(email, api_token)


def validate_worklogs_vs_issues(conn, detailed: bool = False) -> Dict[str, Any]:
    """
    Check for worklogs referencing non-existent issues.
    Returns summary statistics and list of orphaned issue references.
    """
    print("\n" + "=" * 80)
    print("VALIDATION: Worklogs vs Issues")
    print("=" * 80)

    cur = conn.cursor()

    # Get overall statistics
    cur.execute("""
        WITH worklog_issues AS (
            SELECT DISTINCT
                w.issue_id,
                w.issue_key,
                COUNT(*) as worklog_count
            FROM raw_jira.worklogs w
            GROUP BY w.issue_id, w.issue_key
        ),
        validation AS (
            SELECT
                wi.issue_id,
                wi.issue_key,
                wi.worklog_count,
                CASE WHEN i.id IS NULL THEN 'MISSING' ELSE 'EXISTS' END as status
            FROM worklog_issues wi
            LEFT JOIN raw_jira.issues i ON wi.issue_id = i.id
        )
        SELECT
            COUNT(*) as total_issue_refs,
            COUNT(*) FILTER (WHERE status = 'EXISTS') as found_issues,
            COUNT(*) FILTER (WHERE status = 'MISSING') as missing_issues,
            COALESCE(SUM(worklog_count) FILTER (WHERE status = 'MISSING'), 0) as orphaned_worklogs
        FROM validation
    """)

    row = cur.fetchone()
    total_refs, found, missing, orphaned_worklogs = row

    print(f"\n   Total unique issues referenced in worklogs: {total_refs:,}")
    print(f"   Issues found in issues table:              {found:,}")
    print(f"   Issues MISSING from issues table:          {missing:,}")
    print(f"   Worklogs with missing issues:              {orphaned_worklogs:,}")

    integrity_pct = (found / total_refs * 100) if total_refs > 0 else 100
    print(f"\n   Data Integrity Score: {integrity_pct:.1f}%")

    missing_issues_list = []

    if missing > 0:
        print(f"\n   WARNING: {missing:,} issues referenced in worklogs are missing from issues table!")

        # Get top affected projects
        cur.execute("""
            SELECT
                SPLIT_PART(w.issue_key, '-', 1) as project_key,
                COUNT(DISTINCT w.issue_id) as missing_issues,
                COUNT(*) as affected_worklogs
            FROM raw_jira.worklogs w
            LEFT JOIN raw_jira.issues i ON w.issue_id = i.id
            WHERE i.id IS NULL AND w.issue_key IS NOT NULL
            GROUP BY SPLIT_PART(w.issue_key, '-', 1)
            ORDER BY missing_issues DESC
            LIMIT 15
        """)

        print(f"\n   Top 15 Affected Projects:")
        print(f"   {'Project':<12} {'Missing Issues':>15} {'Affected Worklogs':>18}")
        print(f"   {'-'*12} {'-'*15} {'-'*18}")

        for project, miss_issues, aff_worklogs in cur.fetchall():
            print(f"   {project:<12} {miss_issues:>15,} {aff_worklogs:>18,}")

        # Get detailed list of missing issues
        cur.execute("""
            SELECT
                w.issue_id,
                w.issue_key,
                SPLIT_PART(w.issue_key, '-', 1) as project_key,
                COUNT(*) as worklog_count,
                MIN(w.started::date) as first_worklog,
                MAX(w.started::date) as last_worklog,
                COUNT(DISTINCT w.author_id) as unique_authors
            FROM raw_jira.worklogs w
            LEFT JOIN raw_jira.issues i ON w.issue_id = i.id
            WHERE i.id IS NULL
            GROUP BY w.issue_id, w.issue_key
            ORDER BY worklog_count DESC
            LIMIT 100
        """)

        missing_issues_list = []
        for row in cur.fetchall():
            missing_issues_list.append({
                "issue_id": row[0],
                "issue_key": row[1],
                "project_key": row[2],
                "worklog_count": row[3],
                "first_worklog": str(row[4]) if row[4] else None,
                "last_worklog": str(row[5]) if row[5] else None,
                "unique_authors": row[6]
            })

        if detailed:
            print(f"\n   Detailed Missing Issues (top 50):")
            print(f"   {'Issue ID':>10} {'Issue Key':<15} {'Worklogs':>10} {'First Date':>12} {'Last Date':>12} {'Authors':>8}")
            print(f"   {'-'*10} {'-'*15} {'-'*10} {'-'*12} {'-'*12} {'-'*8}")

            for item in missing_issues_list[:50]:
                print(f"   {item['issue_id']:>10} {(item['issue_key'] or 'N/A'):<15} {item['worklog_count']:>10,} {(item['first_worklog'] or 'N/A'):>12} {(item['last_worklog'] or 'N/A'):>12} {item['unique_authors']:>8}")

    cur.close()

    return {
        "total_issue_refs": total_refs,
        "found_issues": found,
        "missing_issues": missing,
        "orphaned_worklogs": orphaned_worklogs,
        "integrity_pct": integrity_pct,
        "missing_issues_list": missing_issues_list
    }


def validate_issues_vs_projects(conn) -> Dict[str, Any]:
    """
    Check for issues referencing non-existent projects.
    """
    print("\n" + "=" * 80)
    print("VALIDATION: Issues vs Projects")
    print("=" * 80)

    cur = conn.cursor()

    cur.execute("""
        WITH validation AS (
            SELECT
                i.project_key,
                i.project_id,
                CASE WHEN p.id IS NULL THEN 'MISSING' ELSE 'EXISTS' END as status
            FROM raw_jira.issues i
            LEFT JOIN raw_jira.projects p ON i.project_id = p.id
        )
        SELECT
            COUNT(*) as total_issues,
            COUNT(*) FILTER (WHERE status = 'EXISTS') as with_project,
            COUNT(*) FILTER (WHERE status = 'MISSING') as missing_project
        FROM validation
    """)

    row = cur.fetchone()
    total, with_proj, missing_proj = row

    print(f"\n   Total issues:                    {total:,}")
    print(f"   Issues with valid project:       {with_proj:,}")
    print(f"   Issues with missing project:     {missing_proj:,}")

    missing_projects = []
    if missing_proj > 0:
        print(f"\n   WARNING: {missing_proj:,} issues reference missing projects!")

        cur.execute("""
            SELECT
                i.project_key,
                i.project_id,
                COUNT(*) as issue_count
            FROM raw_jira.issues i
            LEFT JOIN raw_jira.projects p ON i.project_id = p.id
            WHERE p.id IS NULL
            GROUP BY i.project_key, i.project_id
            ORDER BY issue_count DESC
            LIMIT 20
        """)

        print(f"\n   Missing Projects:")
        for proj_key, proj_id, count in cur.fetchall():
            print(f"   - {proj_key} (ID: {proj_id}): {count:,} issues")
            missing_projects.append({"project_key": proj_key, "project_id": proj_id, "issue_count": count})

    cur.close()

    return {
        "total_issues": total,
        "with_project": with_proj,
        "missing_project": missing_proj,
        "missing_projects": missing_projects
    }


def analyze_issue_id_gaps(conn, detailed: bool = False) -> Dict[str, Any]:
    """
    Analyze gaps in issue IDs to identify potentially missing issues.
    """
    print("\n" + "=" * 80)
    print("VALIDATION: Issue ID Gap Analysis")
    print("=" * 80)

    cur = conn.cursor()

    # Get ID range and count
    cur.execute("""
        SELECT
            MIN(id::integer) as min_id,
            MAX(id::integer) as max_id,
            COUNT(*) as total_count
        FROM raw_jira.issues
        WHERE id ~ '^[0-9]+$'
    """)

    min_id, max_id, total = cur.fetchone()
    expected = max_id - min_id + 1 if max_id and min_id else 0
    missing = expected - total if expected > 0 else 0

    print(f"\n   ID Range: {min_id:,} - {max_id:,}")
    print(f"   Total Issues: {total:,}")
    print(f"   Expected (continuous): {expected:,}")
    print(f"   Gap Count: {missing:,}")

    # Get largest gaps
    cur.execute("""
        WITH issue_ids AS (
            SELECT id::integer as issue_id
            FROM raw_jira.issues
            WHERE id ~ '^[0-9]+$'
            ORDER BY id::integer
        ),
        gaps AS (
            SELECT
                a.issue_id as prev_id,
                MIN(b.issue_id) as next_id,
                MIN(b.issue_id) - a.issue_id - 1 as gap_size
            FROM issue_ids a
            INNER JOIN issue_ids b ON b.issue_id > a.issue_id
            WHERE NOT EXISTS (
                SELECT 1 FROM issue_ids c WHERE c.issue_id = a.issue_id + 1
            )
            GROUP BY a.issue_id
        )
        SELECT prev_id, next_id, gap_size
        FROM gaps
        WHERE gap_size > 50
        ORDER BY gap_size DESC
        LIMIT 20
    """)

    gaps = cur.fetchall()
    gap_list = []
    if gaps:
        print(f"\n   Largest Gaps (>50 IDs):")
        print(f"   {'From ID':>12} {'To ID':>12} {'Gap Size':>12}")
        print(f"   {'-'*12} {'-'*12} {'-'*12}")
        for prev_id, next_id, gap_size in gaps:
            print(f"   {prev_id:>12,} {next_id:>12,} {gap_size:>12,}")
            gap_list.append({"from_id": prev_id, "to_id": next_id, "gap_size": gap_size})

    cur.close()

    return {
        "min_id": min_id,
        "max_id": max_id,
        "total_issues": total,
        "expected": expected,
        "missing_ids": missing,
        "gaps": gap_list
    }


def analyze_worklog_id_gaps(conn, detailed: bool = False) -> Dict[str, Any]:
    """
    Analyze gaps in worklog IDs to identify potentially missing worklogs.
    Uses a simplified approach for performance.
    """
    print("\n" + "=" * 80)
    print("VALIDATION: Worklog ID Gap Analysis")
    print("=" * 80)

    cur = conn.cursor()

    # Get ID range and count
    cur.execute("""
        SELECT
            MIN(id::bigint) as min_id,
            MAX(id::bigint) as max_id,
            COUNT(*) as total_count
        FROM raw_jira.worklogs
        WHERE id ~ '^[0-9]+$'
    """)

    min_id, max_id, total = cur.fetchone()
    expected = max_id - min_id + 1 if max_id and min_id else 0
    missing = expected - total if expected > 0 else 0
    gap_pct = (missing / expected * 100) if expected > 0 else 0

    print(f"\n   ID Range: {min_id:,} - {max_id:,}")
    print(f"   Total Worklogs: {total:,}")
    print(f"   Expected (continuous): {expected:,}")
    print(f"   Gap Count: {missing:,} ({gap_pct:.1f}%)")

    # Note: Worklog IDs are not sequential in Jira - gaps are expected
    print(f"\n   Note: Worklog IDs are assigned by Jira and gaps are normal")
    print(f"   (worklogs may be deleted, or IDs shared across Jira instances)")

    cur.close()

    return {
        "min_id": min_id,
        "max_id": max_id,
        "total_worklogs": total,
        "expected": expected,
        "missing_ids": missing,
        "gap_pct": gap_pct,
        "gaps": []
    }


def analyze_authors_with_missing_issues(conn, detailed: bool = False) -> Dict[str, Any]:
    """
    Analyze authors who have worklogs referencing missing issues.
    """
    print("\n" + "=" * 80)
    print("VALIDATION: Authors with Missing Issue Worklogs")
    print("=" * 80)

    cur = conn.cursor()

    cur.execute("""
        SELECT
            w.author_id,
            w.author_name,
            COUNT(DISTINCT w.issue_id) as missing_issues,
            COUNT(*) as worklog_count,
            MIN(w.started::date) as first_worklog,
            MAX(w.started::date) as last_worklog
        FROM raw_jira.worklogs w
        LEFT JOIN raw_jira.issues i ON w.issue_id = i.id
        WHERE i.id IS NULL
        GROUP BY w.author_id, w.author_name
        ORDER BY worklog_count DESC
        LIMIT 30
    """)

    authors = []
    print(f"\n   Top 30 Authors with Worklogs on Missing Issues:")
    print(f"   {'Author ID':<40} {'Name':<25} {'Missing':>8} {'Worklogs':>10} {'First':>12} {'Last':>12}")
    print(f"   {'-'*40} {'-'*25} {'-'*8} {'-'*10} {'-'*12} {'-'*12}")

    for row in cur.fetchall():
        author_id, author_name, missing_issues, worklog_count, first_wl, last_wl = row
        author_id_display = (author_id or 'N/A')[:40]
        author_name_display = (author_name or 'Unknown')[:25]
        first_str = str(first_wl) if first_wl else 'N/A'
        last_str = str(last_wl) if last_wl else 'N/A'

        print(f"   {author_id_display:<40} {author_name_display:<25} {missing_issues:>8,} {worklog_count:>10,} {first_str:>12} {last_str:>12}")

        authors.append({
            "author_id": author_id,
            "author_name": author_name,
            "missing_issues": missing_issues,
            "worklog_count": worklog_count,
            "first_worklog": first_str,
            "last_worklog": last_str
        })

    cur.close()

    return {"authors": authors}


def analyze_worklogs_by_filters(conn, detailed: bool = False) -> Dict[str, Any]:
    """
    Analyze worklogs with missing issues by various filters.
    """
    print("\n" + "=" * 80)
    print("ANALYSIS: Worklogs with Missing Issues by Filters")
    print("=" * 80)

    cur = conn.cursor()

    # By date range
    print("\n   By Worklog Date (started):")
    cur.execute("""
        SELECT
            TO_CHAR(DATE_TRUNC('month', w.started::timestamp), 'YYYY-MM') as month,
            COUNT(DISTINCT w.issue_id) as missing_issues,
            COUNT(*) as worklogs
        FROM raw_jira.worklogs w
        LEFT JOIN raw_jira.issues i ON w.issue_id = i.id
        WHERE i.id IS NULL
        AND w.started >= '2024-01-01'
        GROUP BY DATE_TRUNC('month', w.started::timestamp)
        ORDER BY DATE_TRUNC('month', w.started::timestamp) DESC
        LIMIT 15
    """)

    print(f"   {'Month':>10} {'Missing Issues':>15} {'Worklogs':>12}")
    print(f"   {'-'*10} {'-'*15} {'-'*12}")

    by_month = []
    for month, issues, worklogs in cur.fetchall():
        if month:
            print(f"   {month:>10} {issues:>15,} {worklogs:>12,}")
            by_month.append({"month": month, "missing_issues": issues, "worklogs": worklogs})

    cur.close()

    return {"by_month": by_month}


def get_missing_issue_ids(conn, limit: int = 1000) -> List[Dict[str, Any]]:
    """
    Get list of issue IDs from worklogs that are missing in issues table.
    """
    cur = conn.cursor()

    cur.execute("""
        SELECT
            w.issue_id,
            w.issue_key,
            SPLIT_PART(w.issue_key, '-', 1) as project_key,
            COUNT(*) as worklog_count
        FROM raw_jira.worklogs w
        LEFT JOIN raw_jira.issues i ON w.issue_id = i.id
        WHERE i.id IS NULL AND w.issue_id IS NOT NULL
        GROUP BY w.issue_id, w.issue_key
        ORDER BY worklog_count DESC
        LIMIT %s
    """, (limit,))

    issues = []
    for row in cur.fetchall():
        issues.append({
            "issue_id": row[0],
            "issue_key": row[1],
            "project_key": row[2],
            "worklog_count": row[3]
        })

    cur.close()
    return issues


def verify_issues_in_jira(issue_ids: List[Dict[str, Any]], max_verify: int = 20) -> Dict[str, Any]:
    """
    Verify if missing issues actually exist in Jira.
    """
    print("\n" + "=" * 80)
    print("VERIFICATION: Checking Missing Issues in Jira API")
    print("=" * 80)

    base_url, auth = get_jira_auth()

    if not base_url:
        print("   ERROR: Jira credentials not configured")
        return {"verified": 0, "exists": 0, "not_found": 0}

    sample = issue_ids[:max_verify]
    print(f"\n   Verifying {len(sample)} sample issues in Jira...")

    exists = 0
    not_found = 0
    errors = 0

    results = []
    for item in sample:
        issue_id = item["issue_id"]
        try:
            url = f"{base_url}/rest/api/3/issue/{issue_id}"
            response = requests.get(url, auth=auth, timeout=10)

            if response.status_code == 200:
                data = response.json()
                key = data.get('key', 'N/A')
                created = data.get('fields', {}).get('created', 'N/A')[:10]
                status_name = data.get('fields', {}).get('status', {}).get('name', 'N/A')
                results.append({
                    "issue_id": issue_id,
                    "issue_key": key,
                    "status": "EXISTS",
                    "created": created,
                    "jira_status": status_name
                })
                exists += 1
            elif response.status_code == 404:
                results.append({
                    "issue_id": issue_id,
                    "issue_key": item.get("issue_key", "N/A"),
                    "status": "NOT_FOUND",
                    "created": None,
                    "jira_status": None
                })
                not_found += 1
            else:
                results.append({
                    "issue_id": issue_id,
                    "issue_key": item.get("issue_key", "N/A"),
                    "status": f"HTTP_{response.status_code}",
                    "created": None,
                    "jira_status": None
                })
                errors += 1

            time.sleep(0.1)  # Rate limiting

        except Exception as e:
            results.append({
                "issue_id": issue_id,
                "issue_key": item.get("issue_key", "N/A"),
                "status": f"ERROR",
                "created": None,
                "jira_status": str(e)[:30]
            })
            errors += 1

    print(f"\n   {'Issue ID':>12} {'Key':<15} {'Status':<12} {'Created':>12} {'Jira Status':<15}")
    print(f"   {'-'*12} {'-'*15} {'-'*12} {'-'*12} {'-'*15}")

    for r in results[:15]:
        print(f"   {r['issue_id']:>12} {(r['issue_key'] or 'N/A'):<15} {r['status']:<12} {(r['created'] or 'N/A'):>12} {(r['jira_status'] or 'N/A'):<15}")

    if len(results) > 15:
        print(f"   ... and {len(results) - 15} more")

    print(f"\n   Summary:")
    print(f"   - Exists in Jira: {exists}")
    print(f"   - Not Found: {not_found}")
    print(f"   - Errors: {errors}")

    return {
        "verified": len(sample),
        "exists": exists,
        "not_found": not_found,
        "errors": errors,
        "results": results
    }


def generate_fix_commands(
    missing_issues: List[Dict[str, Any]],
    missing_projects: List[Dict[str, Any]],
    verification_results: Optional[Dict[str, Any]] = None
) -> List[str]:
    """
    Generate DLT script commands to fix missing data.
    """
    print("\n" + "=" * 80)
    print("SUGGESTED FIX COMMANDS")
    print("=" * 80)

    commands = []

    # Group missing issues by project
    projects_with_missing = {}
    for item in missing_issues:
        proj = item.get("project_key") or "UNKNOWN"
        if proj not in projects_with_missing:
            projects_with_missing[proj] = {"issues": [], "worklog_count": 0}
        projects_with_missing[proj]["issues"].append(item)
        projects_with_missing[proj]["worklog_count"] += item.get("worklog_count", 0)

    # Sort by worklog count
    sorted_projects = sorted(
        projects_with_missing.items(),
        key=lambda x: x[1]["worklog_count"],
        reverse=True
    )

    print(f"\n   1. LOAD MISSING ISSUES BY KEY (High Priority)")
    print(f"   " + "-" * 60)

    # Generate commands for top issues
    top_issues = sorted(missing_issues, key=lambda x: x.get("worklog_count", 0), reverse=True)[:20]

    for item in top_issues:
        issue_key = item.get("issue_key")
        if issue_key:
            cmd = f"docker exec ppm-dlt python /app/jira/jira_issues.py --issue-key={issue_key}"
            commands.append(cmd)
            print(f"   # {issue_key} ({item.get('worklog_count', 0):,} worklogs)")
            print(f"   {cmd}")

    print(f"\n   2. LOAD ISSUES BY DATE RANGE (For bulk missing issues)")
    print(f"   " + "-" * 60)

    # Find date ranges with missing issues
    date_ranges = set()
    for item in missing_issues:
        # We don't have dates in this list, but suggest common ranges
        pass

    # Suggest date-based extraction
    cmd_2020 = "docker exec ppm-dlt python /app/jira/jira_issues.py --mode=initial --start-date=2020-01-01 --end-date=2020-12-31"
    cmd_2021 = "docker exec ppm-dlt python /app/jira/jira_issues.py --mode=initial --start-date=2021-01-01 --end-date=2021-12-31"
    cmd_2022 = "docker exec ppm-dlt python /app/jira/jira_issues.py --mode=initial --start-date=2022-01-01 --end-date=2022-12-31"
    cmd_2023 = "docker exec ppm-dlt python /app/jira/jira_issues.py --mode=initial --start-date=2023-01-01 --end-date=2023-12-31"
    cmd_2024 = "docker exec ppm-dlt python /app/jira/jira_issues.py --mode=initial --start-date=2024-01-01 --end-date=2024-12-31"
    cmd_2025 = "docker exec ppm-dlt python /app/jira/jira_issues.py --mode=initial --start-date=2025-01-01 --end-date=2025-12-31"

    print(f"   # Load all issues by year")
    print(f"   {cmd_2020}")
    print(f"   {cmd_2021}")
    print(f"   {cmd_2022}")
    print(f"   {cmd_2023}")
    print(f"   {cmd_2024}")
    print(f"   {cmd_2025}")

    commands.extend([cmd_2020, cmd_2021, cmd_2022, cmd_2023, cmd_2024, cmd_2025])

    print(f"\n   3. RELOAD WORKLOGS FOR SPECIFIC ISSUES")
    print(f"   " + "-" * 60)

    for item in top_issues[:10]:
        issue_key = item.get("issue_key")
        if issue_key:
            cmd = f"docker exec ppm-dlt python /app/jira/jira_worklogs_optimized.py --issue-key={issue_key}"
            commands.append(cmd)
            print(f"   # Reload worklogs for {issue_key}")
            print(f"   {cmd}")

    print(f"\n   4. RELOAD PROJECTS")
    print(f"   " + "-" * 60)

    cmd_projects = "docker exec ppm-dlt python /app/jira/jira_projects.py --mode=initial"
    commands.append(cmd_projects)
    print(f"   # Reload all projects")
    print(f"   {cmd_projects}")

    print(f"\n   5. UPDATE WORKLOGS WITH MISSING ISSUE_KEY (SQL Fix)")
    print(f"   " + "-" * 60)

    sql_fix = """docker exec ppm-postgres psql -U ppm_user -d ppm_datawarehouse -c "
UPDATE raw_jira.worklogs w
SET issue_key = i.key
FROM raw_jira.issues i
WHERE w.issue_id = i.id
AND (w.issue_key IS NULL OR w.issue_key = '')
AND i.key IS NOT NULL;"
"""
    print(f"   # Update worklogs with NULL issue_key from issues table")
    print(f"   {sql_fix}")
    commands.append(sql_fix)

    return commands


def export_missing_data(
    missing_issues: List[Dict[str, Any]],
    worklogs_result: Dict[str, Any],
    commands: List[str]
) -> None:
    """
    Export missing data to JSON files for further processing.
    """
    print("\n" + "=" * 80)
    print("EXPORTING DATA")
    print("=" * 80)

    # Export missing issues
    with open(MISSING_ISSUES_FILE, 'w') as f:
        json.dump(missing_issues, f, indent=2, default=str)
    print(f"   Exported {len(missing_issues)} missing issues to: {MISSING_ISSUES_FILE}")

    # Export fix commands
    with open(FIX_COMMANDS_FILE, 'w') as f:
        f.write("#!/bin/bash\n")
        f.write("# Generated fix commands for Jira data\n")
        f.write(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        for cmd in commands:
            f.write(f"{cmd}\n")
    print(f"   Exported fix commands to: {FIX_COMMANDS_FILE}")


def generate_validation_report(conn, detailed: bool = False) -> Dict[str, Any]:
    """
    Generate comprehensive validation report.
    """
    print("\n" + "=" * 80)
    print("JIRA DATA VALIDATION REPORT")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # Run all validations
    worklogs_result = validate_worklogs_vs_issues(conn, detailed)
    issues_result = validate_issues_vs_projects(conn)
    issue_gaps_result = analyze_issue_id_gaps(conn, detailed)
    worklog_gaps_result = analyze_worklog_id_gaps(conn, detailed)

    # Analyze authors
    authors_result = analyze_authors_with_missing_issues(conn, detailed)

    # Analyze filters
    filters_result = analyze_worklogs_by_filters(conn, detailed)

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    overall_status = "PASS"
    issues = []

    if worklogs_result['missing_issues'] > 0:
        overall_status = "FAIL"
        issues.append(f"- {worklogs_result['missing_issues']:,} issues referenced in worklogs are missing")
        issues.append(f"  -> {worklogs_result['orphaned_worklogs']:,} orphaned worklogs")

    if issues_result['missing_project'] > 0:
        if overall_status != "FAIL":
            overall_status = "WARNING"
        issues.append(f"- {issues_result['missing_project']:,} issues reference missing projects")

    if worklog_gaps_result['gap_pct'] > 10:
        if overall_status != "FAIL":
            overall_status = "WARNING"
        issues.append(f"- {worklog_gaps_result['gap_pct']:.1f}% worklog ID gaps detected")

    print(f"\n   Overall Status: {overall_status}")
    print(f"   Data Integrity: {worklogs_result['integrity_pct']:.1f}%")

    if issues:
        print(f"\n   Issues Found:")
        for issue in issues:
            print(f"   {issue}")
    else:
        print(f"\n   No data integrity issues found!")

    print("\n" + "=" * 80)

    return {
        "status": overall_status,
        "worklogs_validation": worklogs_result,
        "issues_validation": issues_result,
        "issue_gaps_analysis": issue_gaps_result,
        "worklog_gaps_analysis": worklog_gaps_result,
        "authors_analysis": authors_result,
        "filters_analysis": filters_result,
        "issues_found": issues
    }


def main():
    parser = argparse.ArgumentParser(description="Jira Data Validation Script")
    parser.add_argument("--detailed", action="store_true",
                        help="Show detailed lists of missing issues, authors, etc.")
    parser.add_argument("--verify-in-jira", action="store_true",
                        help="Verify missing issues exist in Jira API")
    parser.add_argument("--max-verify", type=int, default=30,
                        help="Maximum issues to verify in Jira API (default: 30)")
    parser.add_argument("--export-missing", action="store_true",
                        help="Export missing data to JSON files")
    parser.add_argument("--show-commands", action="store_true",
                        help="Show suggested DLT commands to fix missing data")
    args = parser.parse_args()

    try:
        conn = get_db_connection()

        # Run validation report
        report = generate_validation_report(conn, detailed=args.detailed)

        # Get missing issues for further processing
        missing_issues = get_missing_issue_ids(conn, limit=500)

        # Optionally verify in Jira
        verification_results = None
        if args.verify_in_jira:
            verification_results = verify_issues_in_jira(missing_issues, max_verify=args.max_verify)

        # Generate fix commands
        commands = []
        if args.show_commands or args.export_missing:
            commands = generate_fix_commands(
                missing_issues,
                report['issues_validation'].get('missing_projects', []),
                verification_results
            )

        # Export data
        if args.export_missing:
            export_missing_data(missing_issues, report['worklogs_validation'], commands)

        conn.close()

        # Exit with error code if validation failed
        if report['status'] == 'FAIL':
            sys.exit(1)

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
