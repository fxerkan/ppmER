"""
SharePoint Proje Inv DLT Pipeline

Extracts all items from the "Proje Inv" SharePoint list and loads them to PostgreSQL.
Uses MSAL + Microsoft Graph API for authentication.

Pipeline Modes:
    - initial: Full replace of the table (drops and recreates)
    - daily: Merge mode - updates existing records, handles schema evolution

Usage:
    # From command line (default: initial mode)
    docker exec ppm-dlt python /app/sharepoint/shrp_proje_inv.py

    # With specific mode
    docker exec ppm-dlt python /app/sharepoint/shrp_proje_inv.py --mode=daily
    docker exec ppm-dlt python /app/sharepoint/shrp_proje_inv.py --mode=initial

    # From Mage (via dlt_runner utility)
    from utils.dlt_runner import run_dlt_script
    result = run_dlt_script(
        script_path='/home/dlt/sharepoint/shrp_proje_inv.py',
        target_table='raw_sharepoint.proje_inv',
        extra_args=['--mode=daily']
    )

Features:
    - Schema evolution: Creates table if not exists
    - Handles field additions/removals automatically
    - Dynamic field discovery from SharePoint
    - Automatic pagination for large lists
"""

import dlt
from dlt.common.schema.typing import TWriteDisposition
import os
import sys
import argparse
from typing import List, Dict, Any
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dlt_utils import (
    get_postgres_connection,
    table_exists,
    sync_dlt_state_with_database,
    determine_write_disposition
)
from sharepoint.sharepoint_auth_msal import SharePointClient

# ===== CONFIGURATION =====
SHAREPOINT_LIST_TITLE = "Proje Inv"
TABLE_NAME = "proje_inv"
SCHEMA_NAME = "raw_sharepoint"
PIPELINE_NAME = "shrp_proje_inv"


def create_proje_inv_resource(write_disposition: TWriteDisposition):
    """
    Factory function to create dlt resource with dynamic write disposition.
    """
    @dlt.resource(name=TABLE_NAME, write_disposition=write_disposition, primary_key="id")
    def proje_inv_resource():
        """
        dlt resource for SharePoint Proje Inv list.
        """
        print(f"Connecting to SharePoint via MSAL + Graph API...")
        client = SharePointClient(verbose=False)

        print(f"\nFetching all items from '{SHAREPOINT_LIST_TITLE}'...")
        items = client.get_list_items(SHAREPOINT_LIST_TITLE)

        print(f"✅ Fetched {len(items)} items from {SHAREPOINT_LIST_TITLE}")
        for item in items:
            item['_etl_date'] = datetime.now().isoformat()
            yield item

    return proje_inv_resource


def run_pipeline(mode: str = "initial"):
    """
    Run the SharePoint Proje Inv pipeline.

    Args:
        mode: 'initial' for full replace, 'daily' for merge/upsert
    """
    print("=" * 80)
    print(f"SharePoint Proje Inv Pipeline - Mode: {mode.upper()}")
    print("=" * 80)
    print(f"   List: {SHAREPOINT_LIST_TITLE}")
    print(f"   Target: {SCHEMA_NAME}.{TABLE_NAME}")
    print("=" * 80)
    print("")

    # Determine write disposition based on mode and table existence
    if mode == "initial":
        write_disposition: TWriteDisposition = "replace"
        print(f"Using REPLACE mode (initial load)")
    else:
        write_disposition = determine_write_disposition(SCHEMA_NAME, TABLE_NAME, default_mode="merge")

    # Create the pipeline
    pipeline = dlt.pipeline(
        pipeline_name=PIPELINE_NAME,
        destination="postgres",
        dataset_name=SCHEMA_NAME
    )

    # For replace mode or if table doesn't exist, sync DLT state
    if write_disposition == "replace":
        sync_dlt_state_with_database(pipeline, SCHEMA_NAME, TABLE_NAME)
        # Recreate pipeline after state reset
        pipeline = dlt.pipeline(
            pipeline_name=PIPELINE_NAME,
            destination="postgres",
            dataset_name=SCHEMA_NAME
        )

    # Create resource with appropriate write disposition
    proje_inv_res = create_proje_inv_resource(write_disposition)
    data = proje_inv_res()

    print(f"\n💾 Loading data to database ({write_disposition} mode)...")
    load_info = pipeline.run(data)

    # Verify load success
    if load_info.has_failed_jobs:
        print("\n" + "=" * 80)
        print("❌ LOAD FAILED!")
        print("=" * 80)
        for package in load_info.load_packages:
            for job in package.jobs.get("failed_jobs", []):
                print(f"   Failed: {job.file_path}")
                if hasattr(job, 'failed_message'):
                    print(f"   Error: {job.failed_message}")
        raise Exception("DLT load failed with failed jobs")

    print("\n" + "=" * 80)
    print("✅ SharePoint Proje Inv Load Completed!")
    print("=" * 80)
    print(f"   Pipeline: {load_info.pipeline.pipeline_name}")
    print(f"   Dataset: {load_info.pipeline.dataset_name}")
    print(f"   Table: {SCHEMA_NAME}.{TABLE_NAME}")
    print(f"   Mode: {write_disposition}")
    print("=" * 80)

    return load_info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SharePoint Proje Inv DLT Pipeline")
    parser.add_argument(
        "--mode",
        choices=["initial", "daily"],
        default="initial",
        help="Pipeline mode: 'initial' for full replace, 'daily' for merge/upsert"
    )
    args = parser.parse_args()

    run_pipeline(mode=args.mode)
