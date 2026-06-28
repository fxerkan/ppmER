"""
SharePoint Calculation Period DLT Pipeline

Extracts all items from the "Calc Period" SharePoint list and loads them to PostgreSQL.
Uses MSAL + Microsoft Graph API for authentication.
"""

import dlt
from dlt.common.schema.typing import TWriteDisposition
import os
import sys
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dlt_utils import (
    table_exists,
    sync_dlt_state_with_database,
    determine_write_disposition
)
from sharepoint.sharepoint_auth_msal import SharePointClient

# ===== CONFIGURATION =====
SHAREPOINT_LIST_TITLE = "Calculation Period"
TABLE_NAME = "calculation_period"
SCHEMA_NAME = "raw_sharepoint"
PIPELINE_NAME = "shrp_calculation_period"


def create_calculation_period_resource(write_disposition: TWriteDisposition):
    """Factory function to create dlt resource with dynamic write disposition."""
    @dlt.resource(name=TABLE_NAME, write_disposition=write_disposition, primary_key="id")
    def calculation_period_resource():
        """dlt resource for SharePoint Calc Period list."""
        print(f"Connecting to SharePoint via MSAL + Graph API...")
        client = SharePointClient(verbose=False)

        print(f"\nFetching all items from '{SHAREPOINT_LIST_TITLE}'...")
        items = client.get_list_items(SHAREPOINT_LIST_TITLE)

        print(f"✅ Fetched {len(items)} items from {SHAREPOINT_LIST_TITLE}")
        for item in items:
            item['_etl_date'] = datetime.now().isoformat()
            yield item

    return calculation_period_resource


def run_pipeline(mode: str = "initial"):
    """Run the SharePoint Calc Period pipeline."""
    print("=" * 80)
    print(f"SharePoint Calc Period Pipeline - Mode: {mode.upper()}")
    print("=" * 80)
    print(f"   List: {SHAREPOINT_LIST_TITLE}")
    print(f"   Target: {SCHEMA_NAME}.{TABLE_NAME}")
    print("=" * 80)

    if mode == "initial":
        write_disposition: TWriteDisposition = "replace"
        print(f"Using REPLACE mode (initial load)")
    else:
        write_disposition = determine_write_disposition(SCHEMA_NAME, TABLE_NAME, default_mode="merge")

    pipeline = dlt.pipeline(
        pipeline_name=PIPELINE_NAME,
        destination="postgres",
        dataset_name=SCHEMA_NAME
    )

    if write_disposition == "replace":
        sync_dlt_state_with_database(pipeline, SCHEMA_NAME, TABLE_NAME)
        pipeline = dlt.pipeline(
            pipeline_name=PIPELINE_NAME,
            destination="postgres",
            dataset_name=SCHEMA_NAME
        )

    calculation_period_res = create_calculation_period_resource(write_disposition)
    data = calculation_period_res()

    print(f"\n💾 Loading data to database ({write_disposition} mode)...")
    load_info = pipeline.run(data)

    if load_info.has_failed_jobs:
        print("\n" + "=" * 80)
        print("❌ LOAD FAILED!")
        print("=" * 80)
        raise Exception("DLT load failed with failed jobs")

    print("\n" + "=" * 80)
    print("✅ SharePoint Calc Period Load Completed!")
    print("=" * 80)
    print(f"   Table: {SCHEMA_NAME}.{TABLE_NAME}")
    print(f"   Mode: {write_disposition}")
    print("=" * 80)

    return load_info


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SharePoint Calc Period DLT Pipeline")
    parser.add_argument("--mode", choices=["initial", "daily"], default="initial",
                        help="Pipeline mode: 'initial' for full replace, 'daily' for merge/upsert")
    args = parser.parse_args()
    run_pipeline(mode=args.mode)
