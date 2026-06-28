"""
SharePoint CAPEX/OPEX Adjustment DLT Pipeline

Extracts data from "capex_opex_adjustment.xlsx" Excel file stored in SharePoint Document Library
and loads it to PostgreSQL.

The Excel file contains CAPEX/OPEX adjustment data that needs to be loaded into raw_sharepoint schema.
"""

import dlt
from dlt.common.schema.typing import TWriteDisposition
import os
import sys
import argparse
from datetime import datetime
import requests
import pandas as pd
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dlt_utils import (
    table_exists,
    sync_dlt_state_with_database,
    determine_write_disposition
)
from sharepoint.sharepoint_auth_msal import SharePointClient, get_access_token, get_sharepoint_credentials

# ===== CONFIGURATION =====
SHAREPOINT_DRIVE_NAME = "Belgeler"  # SharePoint drive/library name
SHAREPOINT_FILE_PATH = "/capex_opex_adjustment.xlsx"  # Path relative to the drive
SHEET_NAME = "Adjustment"  # Sheet name in Excel file - UPDATE IF DIFFERENT
TABLE_NAME = "capex_opex_adjustment"
SCHEMA_NAME = "raw_sharepoint"
PIPELINE_NAME = "shrp_capex_opex_adjustment"


def download_excel_file_from_sharepoint(site_id: str, drive_name: str, file_path: str, access_token: str) -> bytes:
    """
    Download an Excel file from SharePoint document library using Microsoft Graph API.

    Args:
        site_id: SharePoint site ID
        drive_name: Name of the drive/library (e.g., "Belgeler")
        file_path: Path to the file relative to the drive (e.g., "/capex_opex_adjustment.xlsx")
        access_token: Access token for Graph API

    Returns:
        File content as bytes
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    # First, get all drives and find the one we need
    drives_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives"
    response = requests.get(drives_url, headers=headers)

    if response.status_code != 200:
        raise Exception(f"Failed to get drives: {response.status_code} - {response.text}")

    drives = response.json().get("value", [])
    drive_id = None

    for drive in drives:
        if drive.get("name") == drive_name:
            drive_id = drive.get("id")
            print(f"   Found drive '{drive_name}' with ID: {drive_id}")
            break

    if not drive_id:
        available_drives = [d.get("name") for d in drives]
        raise Exception(f"Drive '{drive_name}' not found. Available drives: {available_drives}")

    # Now get the file content using the drive ID and file path
    file_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives/{drive_id}/root:{file_path}:/content"

    print(f"   Downloading file from drive '{drive_name}': {file_path}")
    response = requests.get(file_url, headers=headers)

    if response.status_code == 200:
        print(f"   File downloaded successfully ({len(response.content)} bytes)")
        return response.content
    else:
        raise Exception(f"Failed to download file: {response.status_code} - {response.text}")


def read_excel_from_bytes(file_content: bytes, sheet_name: str) -> pd.DataFrame:
    """
    Read Excel file from bytes into pandas DataFrame.

    Args:
        file_content: Excel file content as bytes
        sheet_name: Name of the sheet to read

    Returns:
        DataFrame containing the Excel data
    """
    print(f"   Reading Excel sheet: {sheet_name}")

    # Read Excel file from bytes
    excel_file = BytesIO(file_content)
    df = pd.read_excel(excel_file, sheet_name=sheet_name)

    print(f"   Excel data loaded: {len(df)} rows, {len(df.columns)} columns")

    return df


def create_capex_opex_adjustment_resource(write_disposition: TWriteDisposition):
    """Factory function to create dlt resource with dynamic write disposition."""
    @dlt.resource(name=TABLE_NAME, write_disposition=write_disposition)
    def capex_opex_adjustment_resource():
        """dlt resource for SharePoint CAPEX/OPEX adjustment Excel file."""
        print(f"Connecting to SharePoint via MSAL + Graph API...")

        # Get credentials and access token
        creds = get_sharepoint_credentials()
        access_token = get_access_token(
            tenant_id=creds["tenant_id"],
            client_id=creds["client_id"],
            client_secret=creds["client_secret"]
        )

        # Get site ID
        from sharepoint.sharepoint_auth_msal import get_sharepoint_site_id
        site_id = get_sharepoint_site_id(
            tenant_name=creds["tenant_name"],
            site_path=creds["site_path"],
            access_token=access_token
        )

        print(f"\nDownloading Excel file from drive '{SHAREPOINT_DRIVE_NAME}': {SHAREPOINT_FILE_PATH}")

        # Download the Excel file
        file_content = download_excel_file_from_sharepoint(site_id, SHAREPOINT_DRIVE_NAME, SHAREPOINT_FILE_PATH, access_token)

        # Read Excel file into DataFrame
        df = read_excel_from_bytes(file_content, SHEET_NAME)

        # Convert DataFrame to list of dictionaries
        records = df.to_dict(orient='records')

        print(f"Prepared {len(records)} records for loading")

        # Add ETL timestamp to each record
        for record in records:
            record['_etl_date'] = datetime.now().isoformat()
            yield record

    return capex_opex_adjustment_resource


def run_pipeline(mode: str = "initial"):
    """Run the SharePoint CAPEX/OPEX Adjustment pipeline."""
    print("=" * 80)
    print(f"SharePoint CAPEX/OPEX Adjustment Pipeline - Mode: {mode.upper()}")
    print("=" * 80)
    print(f"   Drive: {SHAREPOINT_DRIVE_NAME}")
    print(f"   File: {SHAREPOINT_FILE_PATH}")
    print(f"   Sheet: {SHEET_NAME}")
    print(f"   Target: {SCHEMA_NAME}.{TABLE_NAME}")
    print("=" * 80)

    # Always use REPLACE mode since this is a full extract from Excel file
    # CAPEX/OPEX adjustment data is always a complete snapshot, not incremental
    write_disposition: TWriteDisposition = "replace"
    print(f"Using REPLACE mode (full snapshot from Excel file)")

    # Always sync state to avoid schema version conflicts
    # This ensures clean state management between runs
    pipeline = dlt.pipeline(
        pipeline_name=PIPELINE_NAME,
        destination="postgres",
        dataset_name=SCHEMA_NAME
    )

    sync_dlt_state_with_database(pipeline, SCHEMA_NAME, TABLE_NAME)

    # Recreate pipeline after state sync
    pipeline = dlt.pipeline(
        pipeline_name=PIPELINE_NAME,
        destination="postgres",
        dataset_name=SCHEMA_NAME
    )

    capex_opex_adjustment_res = create_capex_opex_adjustment_resource(write_disposition)
    data = capex_opex_adjustment_res()

    print(f"\nLoading data to database ({write_disposition} mode)...")
    load_info = pipeline.run(data)

    if load_info.has_failed_jobs:
        print("\n" + "=" * 80)
        print("LOAD FAILED!")
        print("=" * 80)
        raise Exception("DLT load failed with failed jobs")

    print("\n" + "=" * 80)
    print("SharePoint CAPEX/OPEX Adjustment Load Completed!")
    print("=" * 80)
    print(f"   Table: {SCHEMA_NAME}.{TABLE_NAME}")
    print(f"   Mode: {write_disposition}")
    print("=" * 80)

    return load_info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SharePoint CAPEX/OPEX Adjustment DLT Pipeline")
    parser.add_argument("--mode", choices=["initial", "daily"], default="initial",
                        help="Pipeline mode: 'initial' for full replace, 'daily' for replace")
    args = parser.parse_args()
    run_pipeline(mode=args.mode)
