{{
    config(
        materialized="incremental",
        schema="core",
        tags=["jira", "core", "fact", "snapshot", "incremental"],
        unique_key="snapshot_key",
        incremental_strategy="merge",
        on_schema_change="append_new_columns",
        merge_exclude_columns=["_snapshot_created_at"],
        indexes=[
            {"columns": ["snapshot_key"], "unique": True},
            {"columns": ["snapshot_period"]},
            {"columns": ["worklog_id"]},
            {"columns": ["period"]},
            {"columns": ["issue_id"]},
            {"columns": ["author_id"]},
        ],
        post_hook="DELETE FROM {{ this }} fs WHERE fs.is_period_locked = false AND NOT EXISTS (SELECT 1 FROM {{ ref('fact_worklogs') }} fw WHERE fw.worklog_id = fs.worklog_id)"
    )
}}

{#
  Worklog Snapshot Fact Table

  Stores worklog data with period-based locking mechanism.

  KEY BEHAVIOR:
  - LOCKED periods (is_locked=true in dim_calc_period):
    Once a period is locked and data is snapshotted, those records are NEVER updated.
    Even if source fact_worklogs data changes, locked period data remains frozen.

  - UNLOCKED periods (is_locked=false in dim_calc_period):
    Data is synced from fact_worklogs on each run. Updates are allowed.

  UNIQUE KEY: snapshot_period + worklog_id
  This ensures each worklog can exist in the snapshot once per period.
#}

with
    calc_periods as (
        select
            period,
            is_locked,
            lock_date
        from {{ ref("dim_calc_period") }}
    ),

    worklogs as (
        select * from {{ ref("fact_worklogs") }}
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

    -- Get worklogs for processable periods only
    snapshot_data as (
        select
            -- Snapshot key (composite: period + worklog_id)
            w.period || '_' || w.worklog_id::text as snapshot_key,

            -- Snapshot period info
            w.period as snapshot_period,
            p.is_locked as is_period_locked,
            p.lock_date as period_lock_date,

            -- All original fact_worklogs columns
            w."period",
            w.trx_date,
            w.worklog_id,
            w.issue_id,
            w.issue_key,
            w.issue_type,
            w.issue_type_id,
            w.issue_type_name,
            w.capex_opex,
            w.is_outsource_inhouse,
            w.issue_type_category,
            w.project_id,
            w.project_key,
            w.project_name,
            w.author_id,
            w.author_name,
            w.author_full_name,
            w.author_email,
            w.author_unit,
            w.author_team,
            w.time_spent_display,
            w.time_spent_seconds,
            w.time_spent_hours,
            w.time_spent_person_days,
            w.epic_id,
            w.epic_key,
            w.epic_name,
            w.category_name,
            w.is_private,
            w.business_line,
            w.customer,
            w.hosting,
            w.portfolio_id,
            w.it_domain,
            w.product,
            w.product_group,
            w.tribe,
            w.financial_code,
            w.open_closed,
            w.app_mgmt_distribution_effort,
            w.itops_distribution_effort,
            w.infosec_distribution_effort,
            w.l1_distribution_effort,
            w.l2_distribution_effort,
            w.work_started_date,
            w.created_date,
            w.updated_date,
            w."_dlt_load_id",

            -- Snapshot metadata
            current_timestamp as _snapshot_created_at,
            current_timestamp as _snapshot_updated_at,
            current_timestamp as _etl_date
        from worklogs w
        inner join periods_to_process p on w.period = p.period
    )

select *
from snapshot_data
