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
            {"columns": ["issue_id"]},
            {"columns": ["issue_key"]},
            {"columns": ["project_key"]},
            {"columns": ["epic_id"]},
        ]
    )
}}

{#
  Issue Dimension Snapshot Table

  Stores issue dimension data with period-based locking mechanism.

  KEY BEHAVIOR:
  - LOCKED periods (is_locked=true in dim_calc_period):
    Once a period is locked and data is snapshotted, those records are NEVER updated.
    Even if source dim_issues data changes, locked period data remains frozen.

  - UNLOCKED periods (is_locked=false in dim_calc_period):
    Data is synced from dim_issues on each run. Updates are allowed.

  UNIQUE KEY: snapshot_period + issue_id
  This ensures each issue can exist in the snapshot once per period.
#}

with
    calc_periods as (
        select
            period,
            is_locked,
            lock_date
        from {{ ref("dim_calc_period") }}
    ),

    issues as (
        select * from {{ ref("dim_issues") }}
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
        where 1=1
          -- Only process periods up to current month (no future periods)
          and cp.period <= to_char(current_date, 'YYYY-MM')
        {% if is_incremental() %}
          -- Exclude periods that are already locked in the snapshot
          -- This is the KEY protection: once locked, never touch again
          and cp.period not in (select snapshot_period from already_locked_periods)
          -- Only process current month and last 2 months for incremental runs
          -- This dramatically reduces processing time
          and cp.period >= to_char(current_date - interval '2 months', 'YYYY-MM')
        {% endif %}
    ),

    -- Join issues with processable periods
    -- Only include issues that were created before or during the period
    -- This prevents massive CROSS JOIN creating millions of unnecessary rows
    snapshot_data as (
        select
            -- Snapshot key (composite: period + issue_id)
            p.period || '_' || i.issue_id::text as snapshot_key,

            -- Snapshot period info
            p.period as snapshot_period,
            p.is_locked as is_period_locked,
            p.lock_date as period_lock_date,

            -- All original dim_issues columns
            i.issue_id,
            i.issue_key,
            i.issue_summary,
            i.issue_type,
            i.issue_type_id,
            i.issue_type_name,
            i.capex_opex,
            i.issue_type_category,
            i.priority,
            i.status_name,
            i.status_category,
            i.resolution,
            i.project_id,
            i.project_key,
            i.project_name,
            i.assignee_id,
            i.assignee_name,
            i.reporter_id,
            i.reporter_name,
            i.creator_id,
            i.creator_name,
            i.parent_id,
            i.parent_key,
            i.is_subtask,
            i.epic_id,
            i.epic_key,
            i.epic_name,
            i.l1_issue_id,
            i.l1_issue_key,
            i.l1_issue_name,
            i.l2_issue_id,
            i.l2_issue_key,
            i.l2_issue_name,
            i.created_date,
            i.updated_date,
            i.resolution_date,
            i.due_date,
            i.total_issue_links,
            i.blocks_count,
            i.duplicates_count,
            i.relates_count,
            i.total_subtasks,
            i.completed_subtasks,
            i.open_subtasks,
            i.subtask_completion_pct,
            i.age_days,
            i.time_to_last_update_days,
            i.time_to_resolution_days,
            i.is_overdue,
            i._dlt_load_id,

            -- Snapshot metadata
            current_timestamp as _snapshot_created_at,
            current_timestamp as _snapshot_updated_at,
            current_timestamp as _etl_date
        from periods_to_process p
        inner join issues i on to_char(i.created_date, 'YYYY-MM') <= p.period
    )

select *
from snapshot_data
