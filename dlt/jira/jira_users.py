"""
Jira Users DLT Pipeline

Extracts ALL users from Jira and loads them to PostgreSQL.
Users always use replace mode since the dataset is small and rarely changes.

Usage:
    docker exec ppm-dlt python /app/jira/users.py
    docker exec ppm-dlt python /app/jira/users.py --mode=initial
    docker exec ppm-dlt python /app/jira/users.py --mode=daily

Note: Both modes use 'replace' since users are a small dataset.
"""

import dlt
from dlt.common.schema.typing import TWriteDisposition
import requests
from requests.auth import HTTPBasicAuth
import os
import sys
import argparse
from typing import List, Dict, Any
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dlt_utils import sync_dlt_state_with_database

# ===== CONFIGURATION =====
TABLE_NAME = "users"
SCHEMA_NAME = "raw_jira"
PIPELINE_NAME = "jira_users"

SELECTED_FIELDS = [
    "accountId",
    "accountType",
    "emailAddress",
    "displayName",
    "active",
    "timeZone",
    "locale",
]


def fetch_all_jira_users(base_url: str, auth: HTTPBasicAuth) -> List[Dict[str, Any]]:
    """Fetch ALL Jira users with pagination."""
    all_users = []
    start_at = 0
    max_results = 100

    print("Fetching ALL users from Jira...")

    while True:
        url = f"{base_url}/rest/api/3/users/search"
        params = {
            "startAt": start_at,
            "maxResults": max_results
        }

        try:
            response = requests.get(url, auth=auth, params=params)
            response.raise_for_status()

            users = response.json()

            if not users:
                break

            # Filter to only selected fields
            if SELECTED_FIELDS:
                filtered_users = []
                for user in users:
                    filtered_user = {
                        field: user.get(field)
                        for field in SELECTED_FIELDS
                        if field in user
                    }
                    filtered_user['_etl_date'] = datetime.now().isoformat()
                    filtered_users.append(filtered_user)
                users = filtered_users

            all_users.extend(users)

            print(f"   Retrieved {len(users)} users (total: {len(all_users)})")

            if len(users) < max_results:
                break

            start_at += max_results

        except requests.exceptions.HTTPError as e:
            print(f"   HTTP Error: {e}")
            print(f"   Note: Some Jira instances restrict user search API")
            break
        except Exception as e:
            print(f"   Error: {e}")
            raise

    return all_users


def run_pipeline(mode: str = "initial"):
    """
    Run the Jira users pipeline.

    Args:
        mode: 'initial' or 'daily' (both use replace mode for users)
    """
    print("=" * 80)
    print(f"Jira Users Pipeline - Mode: {mode.upper()}")
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
        raise ValueError("Missing required environment variables")

    auth = HTTPBasicAuth(email, api_token)

    # Users always use replace mode (small dataset)
    write_disposition: TWriteDisposition = "replace"
    print("Using REPLACE mode (users are always fully refreshed)")

    # Create the pipeline
    pipeline = dlt.pipeline(
        pipeline_name=PIPELINE_NAME,
        destination="postgres",
        dataset_name=SCHEMA_NAME
    )

    # Sync DLT state
    sync_dlt_state_with_database(pipeline, SCHEMA_NAME, TABLE_NAME)
    pipeline = dlt.pipeline(
        pipeline_name=PIPELINE_NAME,
        destination="postgres",
        dataset_name=SCHEMA_NAME
    )

    # Fetch users
    print("\nExtracting Data...")
    users = fetch_all_jira_users(base_url, auth)
    print(f"Fetched {len(users)} users total")

    # Load to PostgreSQL
    print(f"\nLoading to Database ({write_disposition} mode)...")

    load_info = pipeline.run(
        dlt.resource(
            users,
            name=TABLE_NAME,
            write_disposition=write_disposition,
            primary_key="accountId"
        )
    )

    # Verify load success
    if load_info.has_failed_jobs:
        print("\n" + "=" * 80)
        print("LOAD FAILED!")
        print("=" * 80)
        for package in load_info.load_packages:
            for job in package.jobs.get("failed_jobs", []):
                print(f"   Failed: {job.file_path}")
        raise Exception("DLT load failed with failed jobs")

    print("\n" + "=" * 80)
    print("Jira Users Load Completed!")
    print("=" * 80)
    print(f"   Pipeline: {load_info.pipeline.pipeline_name}")
    print(f"   Dataset: {load_info.pipeline.dataset_name}")
    print(f"   Table: {SCHEMA_NAME}.{TABLE_NAME}")
    print(f"   Records: {len(users)} users")
    print("=" * 80)

    return load_info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jira Users DLT Pipeline")
    parser.add_argument(
        "--mode",
        choices=["initial", "daily"],
        default="initial",
        help="Pipeline mode (both use replace for users)"
    )
    args = parser.parse_args()

    run_pipeline(mode=args.mode)
