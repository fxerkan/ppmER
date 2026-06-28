{{
    config(
        materialized="view",
        schema="mart",
        tags=["error_check", "row_count", "data_quality"],
        enaled=false

    )
}}

/*
  ERROR CHECK: Worklogs Row Count Validation (Raw -> Staging -> Core)

  Description:
  Compares row counts across different layers to detect data loss:
  - Raw layer (source)
  - Staging layer
  - Core layer (fact_worklogs)

  Expected Result:
  - Empty result = Row counts match across all layers
  - Rows returned = Mismatches that indicate data loss or duplication

  Impact:
  - Data loss can lead to incomplete financial reports
  - Missing worklogs = understated effort
  - Duplicate records = overstated effort

  Action Required:
  - Investigate ETL transformation logic
  - Review incremental model strategy
  - Check for post-hook DELETE statements
*/

with raw_counts as (
    select
        to_char(work_started_date, 'YYYY-MM') as period,
        count(*) as raw_row_count,
        count(distinct worklog_id) as raw_unique_worklogs
    from {{ source('raw_jira', 'worklogs') }}
    where work_started_date >= '2025-01-01'
    group by to_char(work_started_date, 'YYYY-MM')
),

staging_counts as (
    select
        to_char(work_started_date, 'YYYY-MM') as period,
        count(*) as staging_row_count,
        count(distinct worklog_id) as staging_unique_worklogs
    from {{ ref('stg_jira__worklogs') }}
    where work_started_date >= '2025-01-01'
    group by to_char(work_started_date, 'YYYY-MM')
),

core_counts as (
    select
        period,
        count(*) as core_row_count,
        count(distinct worklog_id) as core_unique_worklogs
    from {{ ref('fact_worklogs') }}
    where trx_date >= '2025-01-01'
    group by period
)

select
    coalesce(r.period, s.period, c.period) as period,
    coalesce(r.raw_row_count, 0) as raw_row_count,
    coalesce(r.raw_unique_worklogs, 0) as raw_unique_worklogs,
    coalesce(s.staging_row_count, 0) as staging_row_count,
    coalesce(s.staging_unique_worklogs, 0) as staging_unique_worklogs,
    coalesce(c.core_row_count, 0) as core_row_count,
    coalesce(c.core_unique_worklogs, 0) as core_unique_worklogs,
    -- Differences
    coalesce(r.raw_row_count, 0) - coalesce(s.staging_row_count, 0) as raw_vs_staging_diff,
    coalesce(s.staging_row_count, 0) - coalesce(c.core_row_count, 0) as staging_vs_core_diff,
    coalesce(r.raw_row_count, 0) - coalesce(c.core_row_count, 0) as raw_vs_core_diff,
    -- Flags
    case
        when coalesce(r.raw_row_count, 0) != coalesce(s.staging_row_count, 0) then 'Raw vs Staging Mismatch'
        when coalesce(s.staging_row_count, 0) != coalesce(c.core_row_count, 0) then 'Staging vs Core Mismatch'
        when coalesce(r.raw_row_count, 0) != coalesce(c.core_row_count, 0) then 'Raw vs Core Mismatch'
        else null
    end as mismatch_type,
    current_timestamp as check_date
from raw_counts r
full outer join staging_counts s on r.period = s.period
full outer join core_counts c on coalesce(r.period, s.period) = c.period
where 1=1
    -- Only show mismatches
    and (
        coalesce(r.raw_row_count, 0) != coalesce(s.staging_row_count, 0)
        or coalesce(s.staging_row_count, 0) != coalesce(c.core_row_count, 0)
        or coalesce(r.raw_row_count, 0) != coalesce(c.core_row_count, 0)
    )
order by period desc
