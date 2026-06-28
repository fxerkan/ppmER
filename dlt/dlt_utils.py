"""
DLT Schema Evolution Utilities

Shared utilities for handling automatic schema evolution in DLT pipelines.
These utilities help pipelines automatically:
- Create tables if they don't exist
- Handle schema changes (new fields, removed fields, type changes)
- Sync DLT internal state with actual database state

Usage:
    from dlt_utils import determine_write_disposition, sync_dlt_state_with_database, get_postgres_connection
"""

import os
import psycopg2
from typing import Literal

# Type alias for write disposition
WriteDisposition = Literal["replace", "merge", "append"]


def get_postgres_connection():
    """
    Get PostgreSQL connection using DLT destination credentials.
    Works both in Docker and local environments.

    Priority order for connection parameters:
    1. DESTINATION__POSTGRES__CREDENTIALS__* (Docker/Mage environment)
    2. POSTGRES_* with EXTERNAL_PORT for local access
    3. Default values for development

    To run locally, use the run_local.sh helper script:
        ./run_local.sh jira_daily_projects.py
    """
    # Determine if running locally (outside Docker) or inside container
    # If DESTINATION__POSTGRES__CREDENTIALS__HOST is set, we're in Docker
    is_docker = os.getenv("DESTINATION__POSTGRES__CREDENTIALS__HOST") is not None

    if is_docker:
        # Docker environment - use DESTINATION env vars (fallback to container defaults)
        host = os.getenv("DESTINATION__POSTGRES__CREDENTIALS__HOST", os.getenv("POSTGRES_HOST", "postgres"))
        port = int(os.getenv("DESTINATION__POSTGRES__CREDENTIALS__PORT", os.getenv("POSTGRES_PORT", "5432")))
    else:
        # Local environment - use POSTGRES_HOST from .env (fallback to localhost for container access)
        env_host = os.getenv("POSTGRES_HOST", "localhost")
        # If host is 'postgres' (Docker internal), we're running locally with sourced .env
        host = "localhost" if env_host == "postgres" else env_host
        port = int(os.getenv("POSTGRES_EXTERNAL_PORT", os.getenv("POSTGRES_PORT", "15432")))

    database = os.getenv("DESTINATION__POSTGRES__CREDENTIALS__DATABASE",
                         os.getenv("POSTGRES_DB", "ppm_datawarehouse"))
    username = os.getenv("DESTINATION__POSTGRES__CREDENTIALS__USERNAME",
                         os.getenv("POSTGRES_USER", "ppm_user"))
    password = os.getenv("DESTINATION__POSTGRES__CREDENTIALS__PASSWORD",
                         os.getenv("POSTGRES_PASSWORD", ""))

    return psycopg2.connect(
        host=host,
        port=port,
        database=database,
        user=username,
        password=password
    )


def table_exists(schema: str, table: str) -> bool:
    """
    Check if a table exists in the PostgreSQL database.
    Returns True if table exists, False otherwise.

    Args:
        schema: The database schema name (e.g., 'raw_jira')
        table: The table name (e.g., 'projects')

    Returns:
        bool: True if table exists, False otherwise
    """
    try:
        conn = get_postgres_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
            );
        """, (schema, table))
        exists = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return exists
    except Exception as e:
        print(f"   ⚠️  Could not check table existence: {e}")
        # Default to False to trigger table creation
        return False


def get_table_columns(schema: str, table: str) -> list:
    """
    Get the list of columns for a table in the database.
    Useful for comparing with expected schema.

    Args:
        schema: The database schema name
        table: The table name

    Returns:
        list: List of column names, or empty list if table doesn't exist
    """
    try:
        conn = get_postgres_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position;
        """, (schema, table))
        columns = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return columns
    except Exception as e:
        print(f"   ⚠️  Could not get table columns: {e}")
        return []


def sync_dlt_state_with_database(pipeline, schema: str, table: str) -> bool:
    """
    Sync DLT's internal schema state with the actual database state.
    This is needed when tables are manually dropped or altered outside DLT.

    Args:
        pipeline: The DLT pipeline object
        schema: The database schema name
        table: The table name

    Returns:
        bool: True if state was reset, False otherwise
    """
    if not table_exists(schema, table):
        print(f"   🔄 Table {schema}.{table} not found in database")
        print(f"   🔄 Resetting DLT pipeline state for clean schema inference...")
        try:
            # Drop the pipeline's schema state to force fresh inference
            pipeline.drop()
            print(f"   ✅ Pipeline state reset successfully")
            return True
        except Exception as e:
            print(f"   ⚠️  Could not reset pipeline state: {e}")
            return False
    return False


def determine_write_disposition(schema: str, table: str,
                                default_mode: WriteDisposition = "merge") -> WriteDisposition:
    """
    Determine the appropriate write disposition based on table existence.

    Args:
        schema: The database schema name
        table: The table name
        default_mode: The mode to use when table exists (default: "merge")

    Returns:
        WriteDisposition: Either "replace" (if table missing) or the default_mode

    Behavior:
        - If table exists: use default_mode for incremental updates
        - If table missing: use 'replace' to create table from scratch
    """
    if table_exists(schema, table):
        print(f"   ✅ Table {schema}.{table} exists - using {default_mode.upper()} mode")
        return default_mode
    else:
        print(f"   📝 Table {schema}.{table} does not exist - using REPLACE mode (will create)")
        return "replace"


def run_pipeline_with_schema_evolution(pipeline, resource_factory, schema: str, table: str,
                                       default_mode: WriteDisposition = "merge"):
    """
    Run a DLT pipeline with automatic schema evolution handling.

    This is a convenience function that:
    1. Checks if the table exists
    2. Determines the appropriate write disposition
    3. Syncs DLT state if needed
    4. Creates the resource and runs the pipeline
    5. Verifies the load succeeded

    Args:
        pipeline: The DLT pipeline object (created with dlt.pipeline())
        resource_factory: A function that takes write_disposition and returns a DLT resource
        schema: The database schema name
        table: The table name
        default_mode: The mode to use when table exists (default: "merge")

    Returns:
        LoadInfo: The load information from DLT

    Raises:
        Exception: If the load fails
    """
    import dlt

    # Check table existence and determine write disposition
    print("🔍 Checking database state...")
    write_disposition = determine_write_disposition(schema, table, default_mode)

    # Sync DLT state with database (handles dropped tables)
    if write_disposition == "replace":
        if sync_dlt_state_with_database(pipeline, schema, table):
            # Recreate pipeline after state reset
            pipeline = dlt.pipeline(
                pipeline_name=pipeline.pipeline_name,
                destination=pipeline.destination.destination_name,
                dataset_name=pipeline.dataset_name
            )

    # Create resource with appropriate write disposition
    resource = resource_factory(write_disposition)
    data = resource()

    print(f"\n💾 Loading data to database ({write_disposition} mode)...")
    load_info = pipeline.run(data)

    # Verify load success
    if load_info.has_failed_jobs:
        print("\n" + "=" * 80)
        print("❌ Load had failed jobs!")
        print("=" * 80)
        for package in load_info.load_packages:
            for job in package.jobs.get("failed_jobs", []):
                print(f"   Failed: {job.file_path}")
        raise Exception("DLT load failed")

    return load_info, write_disposition
