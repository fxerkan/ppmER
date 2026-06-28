{{
    config(
        materialized="incremental",
        schema="core",
        tags=["jira", "core", "dim", "snapshot", "incremental"],
        unique_key="snapshot_key",
        incremental_strategy="merge",
        on_schema_change="append_new_columns",
        merge_exclude_columns=["_snapshot_created_at"],
        indexes=[
            {"columns": ["snapshot_key"], "unique": True},
            {"columns": ["snapshot_period"]},
            {"columns": ["project_id"]},
            {"columns": ["project_key"]},
        ]
    )
}}

{#
  Project Dimension Snapshot Table

  Stores project dimension data with period-based locking mechanism.

  KEY BEHAVIOR:
  - LOCKED periods (is_locked=true in dim_calc_period):
    Once a period is locked and data is snapshotted, those records are NEVER updated.
    Even if source dim_projects data changes, locked period data remains frozen.

  - UNLOCKED periods (is_locked=false in dim_calc_period):
    Data is synced from dim_projects on each run. Updates are allowed.

  UNIQUE KEY: snapshot_period + project_id
  This ensures each project can exist in the snapshot once per period.
#}

with
    calc_periods as (
        select
            period,
            is_locked,
            lock_date
        from {{ ref("dim_calc_period") }}
    ),

    projects as (
        select * from {{ ref("dim_projects") }}
    ),

    {% if is_incremental() %}
    -- Get already locked periods that exist in snapshot table
    -- These periods should NEVER be updated
    already_locked_periods as (
        select distinct snapshot_period
        from {{ this }}
        where is_period_locked = true
    ),
    {% endif %}

    -- Determine which periods to process
    periods_to_process as (
        select
            cp.period,
            cp.is_locked,
            cp.lock_date
        from calc_periods cp
        {% if is_incremental() %}
        -- Exclude periods that are already locked in the snapshot
        -- This is the KEY protection: once locked, never touch again
        where cp.period not in (select snapshot_period from already_locked_periods)
        {% endif %}
    ),

    -- Cross join projects with processable periods
    snapshot_data as (
        select
            -- Snapshot key (composite: period + project_id)
            p.period || '_' || pr.project_id::text as snapshot_key,

            -- Snapshot period info
            p.period as snapshot_period,
            p.is_locked as is_period_locked,
            p.lock_date as period_lock_date,

            -- All original dim_projects columns
            pr.project_id,
            pr.project_key,
            pr.project_name,
            pr.project_description,
            pr.project_type,
            pr.category_id,
            pr.category_name,
            pr.is_private,
            pr.business_line,
            pr.customer,
            pr.hosting,
            pr.portfolio_id,
            pr.it_domain,
            pr.product,
            pr.product_group,
            pr.tribe,
            pr.open_closed,
            pr.app_mgmt_distribution_effort,
            pr.itops_distribution_effort,
            pr.infosec_distribution_effort,
            pr.l1_distribution_effort,
            pr.l2_distribution_effort,
            pr.subject_to_l1_distribution,
            pr.subject_to_app_mgmt_distribution,
            pr.subject_to_itops_distribution,
            pr.financial_code,
            pr.financial_report_display,
            pr.devops_deployment_apps,
            pr.total_issues,
            pr.completed_issues,
            pr.in_progress_issues,
            pr.todo_issues,
            pr.unique_assignees,
            pr.unique_reporters,
            pr.first_issue_created_date,
            pr.last_issue_updated_date,
            pr.completion_pct,
            pr.total_worklogs,
            pr.total_hours_logged,
            pr._dlt_load_id,

            -- Snapshot metadata
            current_timestamp as _snapshot_created_at,
            current_timestamp as _snapshot_updated_at,
            current_timestamp as _etl_date
        from periods_to_process p
        cross join projects pr
    )

select *
from snapshot_data
