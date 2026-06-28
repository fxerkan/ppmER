"""
Jira Projects DLT Pipeline

Extracts ALL projects from Jira and loads them to PostgreSQL.

Pipeline Modes:
    - initial: Full replace of the projects table (drops and recreates)
    - daily: Merge mode - updates existing records, handles schema evolution

Usage:
    # From command line (default: initial mode)
    docker exec ppm-dlt python /app/jira/projects.py

    # With specific mode
    docker exec ppm-dlt python /app/jira/projects.py --mode=daily
    docker exec ppm-dlt python /app/jira/projects.py --mode=initial

    # From Mage (via dlt_runner utility)
    from utils.dlt_runner import run_dlt_script
    result = run_dlt_script(
        script_path='/home/dlt/jira/projects.py',
        target_table='raw_jira.projects',
        extra_args=['--mode=daily']
    )

Features:
    - Schema evolution: Creates table if not exists
    - Handles field additions/removals automatically
    - Syncs DLT internal state with actual database state
"""

import dlt
from dlt.common.schema.typing import TWriteDisposition
import requests
from requests.auth import HTTPBasicAuth
import os
import sys
import argparse
from datetime import datetime
from typing import List, Dict, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dlt_utils import (
    get_postgres_connection,
    table_exists,
    sync_dlt_state_with_database,
    determine_write_disposition
)

# ===== CONFIGURATION =====
# Note: Nested fields like issueTypes, components, versions create child tables
# Some nested records may cause issues with _dlt_root_id if data is incomplete
SELECTED_FIELDS = [
    "id",
    "key",
    "name",
    "projectTypeKey",
    "simplified",
    "style",
    "isPrivate",
    "properties",
    "entityId",
    "uuid",
    "description",
    "url",
    "assigneeType",
    "roles",
    "projectCategory",
    "insight",
    # "lead",
    # "avatarUrls",
    # "components",
    # "issueTypes",
    # "versions", 
]

# Nested fields that create child tables - handle separately if needed
# Excluded due to _dlt_root_id issues: "components", "issueTypes", "versions"

# Table configuration
TABLE_NAME = "projects"
SCHEMA_NAME = "raw_jira"
PIPELINE_NAME = "jira_projects"

MAX_RETRIES = 3
RETRY_DELAY = 2


def fetch_all_jira_projects(base_url: str, auth: HTTPBasicAuth) -> List[Dict[str, Any]]:
    """
    Fetch ALL Jira projects with pagination.
    """
    all_projects = []
    start_at = 0
    max_results = 100

    print(f"Fetching ALL projects from Jira...")

    while True:
        url = f"{base_url}/rest/api/3/project/search"
        params = {
            "startAt": start_at,
            "maxResults": max_results,
            "expand": "description,projectKeys,issueTypes"
        }

        try:
            response = requests.get(url, auth=auth, params=params)
            response.raise_for_status()

            data = response.json()
            projects = data.get("values", [])

            # Filter to only selected fields if configured
            if SELECTED_FIELDS:
                filtered_projects = []
                for project in projects:
                    filtered_project = {
                        field: project.get(field)
                        for field in SELECTED_FIELDS
                        if field in project
                    }
                    # Add _etl_date to each project
                    filtered_project['_etl_date'] = datetime.now().isoformat()
                    filtered_projects.append(filtered_project)
                projects = filtered_projects
            else:
                # Add _etl_date if no field filtering
                for project in projects:
                    project['_etl_date'] = datetime.now().isoformat()

            all_projects.extend(projects)

            print(f"   Retrieved {len(projects)} projects (total: {len(all_projects)})")

            is_last = data.get("isLast", True)
            if is_last or not projects:
                break

            start_at += max_results

        except requests.exceptions.HTTPError as e:
            print(f"   HTTP Error: {e}")
            raise
        except Exception as e:
            print(f"   Error: {e}")
            raise

    return all_projects


def create_jira_projects_resource(write_disposition: TWriteDisposition):
    """
    Factory function to create dlt resource with dynamic write disposition.
    """
    @dlt.resource(name=TABLE_NAME, write_disposition=write_disposition, primary_key="id")
    def jira_projects_resource():
        """
        dlt resource for Jira projects.
        """
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
        projects = fetch_all_jira_projects(base_url, auth)

        print(f"Fetched {len(projects)} projects total")
        yield from projects

    return jira_projects_resource


def run_pipeline(mode: str = "initial"):
    """
    Run the Jira projects pipeline.

    Args:
        mode: 'initial' for full replace, 'daily' for merge/upsert

    Note: Projects always use 'replace' mode because:
    1. Project data is small (~500 records)
    2. Projects rarely change
    3. Replace avoids merge complexity with nested tables
    """
    print("=" * 80)
    print(f"Jira Projects Pipeline - Mode: {mode.upper()}")
    print("=" * 80)
    print(f"   Selected fields: {len(SELECTED_FIELDS)}")
    print("=" * 80)
    print("")

    # Projects always use replace mode for simplicity
    # This avoids merge issues with nested tables and is fast since project count is small
    write_disposition: TWriteDisposition = "replace"
    print(f"Using REPLACE mode (projects are always fully refreshed)")

    # Create the pipeline
    pipeline = dlt.pipeline(
        pipeline_name=PIPELINE_NAME,
        destination="postgres",
        dataset_name=SCHEMA_NAME
    )

    # For initial mode or if table doesn't exist, sync DLT state
    if write_disposition == "replace":
        sync_dlt_state_with_database(pipeline, SCHEMA_NAME, TABLE_NAME)
        # Recreate pipeline after state reset
        pipeline = dlt.pipeline(
            pipeline_name=PIPELINE_NAME,
            destination="postgres",
            dataset_name=SCHEMA_NAME
        )

    # Create resource with appropriate write disposition
    projects_resource = create_jira_projects_resource(write_disposition)
    projects_data = projects_resource()

    print(f"\nLoading projects to database ({write_disposition} mode)...")
    load_info = pipeline.run(projects_data)

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
    print("Jira Projects Load Completed!")
    print("=" * 80)
    print(f"   Pipeline: {load_info.pipeline.pipeline_name}")
    print(f"   Dataset: {load_info.pipeline.dataset_name}")
    print(f"   Table: {SCHEMA_NAME}.{TABLE_NAME}")
    print(f"   Mode: {write_disposition}")
    print("=" * 80)

    return load_info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jira Projects DLT Pipeline")
    parser.add_argument(
        "--mode",
        choices=["initial", "daily"],
        default="initial",
        help="Pipeline mode: 'initial' for full replace, 'daily' for merge/upsert"
    )
    args = parser.parse_args()

    run_pipeline(mode=args.mode)
