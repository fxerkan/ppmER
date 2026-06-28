"""
Jira HR Users DLT Pipeline

Extracts HR user data from Jira issues in the "Insan Kaynaklari" project
where "Last Excel[Dropdown]" = Evet.

Pipeline Modes:
    - initial/daily: Both use replace mode (small dataset)

Usage:
    docker exec ppm-dlt python /app/jira/hr_users.py --mode=initial
    docker exec ppm-dlt python /app/jira/hr_users.py --mode=daily
"""

import dlt
import requests
from requests.auth import HTTPBasicAuth
import os
import sys
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dlt_utils import sync_dlt_state_with_database

# ===== CONFIGURATION =====
TABLE_NAME = "hr_users"
SCHEMA_NAME = "raw_jira"
PIPELINE_NAME = "jira_hr_users"

# HR Custom fields mapping
HR_FIELDS = {
    'customfield_10278': 'user_name',
    'customfield_10358': 'manager_director',
    'customfield_10360': 'manager_deputy_gm',
    'customfield_10269': 'name_surname',
    'customfield_10276': 'active_inactive_status',
    'customfield_10274': 'start_time',
    'customfield_10272': 'unit',
    'customfield_10275': 'manages_team',
    'customfield_10359': 'deputy_gm_upper_unit',
    'customfield_10270': 'outsource_inhouse',
    'customfield_10273': 'team',
    'customfield_10289': 'company_info',
    'customfield_10271': 'email',
    'customfield_10295': 'exit_date',
}

JIRA_FIELDS = ["id", "key", "created", "creator"] + list(HR_FIELDS.keys())


def extract_field_value(field_value: Any) -> Optional[str]:
    """Extract value from custom field"""
    if field_value is None:
        return None

    if isinstance(field_value, dict):
        if 'value' in field_value:
            return field_value['value']
        if 'displayName' in field_value:
            return field_value['displayName']
        if 'name' in field_value:
            return field_value['name']
        if 'accountId' in field_value:
            return field_value['accountId']
        return str(field_value)

    if isinstance(field_value, list):
        values = []
        for item in field_value:
            extracted = extract_field_value(item)
            if extracted:
                values.append(extracted)
        return ', '.join(values) if values else None

    return str(field_value) if field_value else None


def parse_datetime(datetime_str: Optional[str]) -> Optional[str]:
    """Parse datetime string from Jira format"""
    if not datetime_str:
        return None
    try:
        datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
        return datetime_str
    except (ValueError, AttributeError):
        return datetime_str


def fetch_hr_users(base_url: str, auth: HTTPBasicAuth) -> List[Dict[str, Any]]:
    """Fetch HR issues from Jira"""
    jql_query = 'project = "İnsan Kaynakları" and "Last Excel[Dropdown]" = Evet'

    print(f"   JQL Query: {jql_query}")
    print(f"   Fields: {len(JIRA_FIELDS)}")

    all_issues = []
    next_page_token = None

    while True:
        url = f"{base_url}/rest/api/3/search/jql"
        params = {
            "jql": jql_query,
            "maxResults": 100,
            "fields": ",".join(JIRA_FIELDS)
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
            print(f"   Retrieved {len(all_issues)}/{total} HR user records")

            next_page_token = data.get("nextPageToken")
            if not next_page_token or not issues:
                break

        except Exception as e:
            print(f"   Error: {e}")
            break

    return all_issues


def transform_hr_user(issue: Dict[str, Any]) -> Dict[str, Any]:
    """Transform a Jira issue into HR user record"""
    fields = issue.get('fields', {})

    creator = fields.get('creator', {})
    user_account_id = creator.get('accountId') if creator else None
    user_name = extract_field_value(fields.get('customfield_10278'))

    hr_record = {
        'issue_id': issue.get('id'),
        'issue_key': issue.get('key'),
        'created_at': parse_datetime(fields.get('created')),
        'user_account_id': user_account_id,
        'user_name': user_name,
        'manager_director': extract_field_value(fields.get('customfield_10358')),
        'manager_deputy_gm': extract_field_value(fields.get('customfield_10360')),
        'name_surname': extract_field_value(fields.get('customfield_10269')),
        'active_inactive_status': extract_field_value(fields.get('customfield_10276')),
        'start_time': extract_field_value(fields.get('customfield_10274')),
        'unit': extract_field_value(fields.get('customfield_10272')),
        'manages_team': extract_field_value(fields.get('customfield_10275')),
        'deputy_gm_upper_unit': extract_field_value(fields.get('customfield_10359')),
        'outsource_inhouse': extract_field_value(fields.get('customfield_10270')),
        'team': extract_field_value(fields.get('customfield_10273')),
        'company_info': extract_field_value(fields.get('customfield_10289')),
        '_etl_date': datetime.now().isoformat(),
        'email': extract_field_value(fields.get('customfield_10271')),
        'exit_date': extract_field_value(fields.get('customfield_10295')),
    }

    return hr_record


def run_pipeline(mode: str = "initial"):
    """Run the Jira HR users pipeline."""
    print("=" * 80)
    print(f"Jira HR Users Pipeline - Mode: {mode.upper()}")
    print("=" * 80)

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

    # HR users always use replace mode
    print("Using REPLACE mode (HR users are always fully refreshed)")

    print("\nExtracting Data...")
    raw_issues = fetch_hr_users(base_url, auth)
    print(f"Fetched {len(raw_issues)} HR user issues")

    # Transform to HR user records
    print("\nProcessing HR users...")
    hr_users = [transform_hr_user(issue) for issue in raw_issues]
    print(f"Transformed {len(hr_users)} HR user records")

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

    print(f"\nLoading to Database...")

    load_info = pipeline.run(
        dlt.resource(hr_users, name=TABLE_NAME, write_disposition="replace", primary_key="issue_key")
    )

    if load_info.has_failed_jobs:
        raise Exception("DLT load failed with failed jobs")

    print("\n" + "=" * 80)
    print("Jira HR Users Load Completed!")
    print("=" * 80)
    print(f"   Table: {SCHEMA_NAME}.{TABLE_NAME}")
    print(f"   Records: {len(hr_users)}")
    print("=" * 80)

    return load_info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jira HR Users DLT Pipeline")
    parser.add_argument("--mode", choices=["initial", "daily"], default="initial")
    args = parser.parse_args()

    run_pipeline(mode=args.mode)
