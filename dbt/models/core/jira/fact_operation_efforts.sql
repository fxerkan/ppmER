{{
    config(
        materialized="table",
        schema="mart",
        tags=["sharepoint", "core", "fact", "operation_efforts"],
        unique_key=["period", "project_id"]
    )
}}

{#
  Operation Efforts Fact Model

  This model brings the operation efforts data from staging to the mart layer,
  providing period-based planned and actual effort hours for projects.

  Key columns:
  - period: YYYY-MM format (e.g., '2025-01')
  - project_id: Jira project ID
  - planned_effort: Planned effort hours for the period
  - actual_effort: Actual effort hours logged for the period
  - variance_hours: Difference between actual and planned (actual - planned)
  - variance_percent: Percentage variance ((actual - planned) / planned * 100)
  - project_name: Project name for reference

  Usage:
  This table can be used for:
  - Operational effort tracking and monitoring
  - Variance analysis (planned vs actual)
  - Resource planning and forecasting
  - Project performance dashboards
#}

with
    staging_efforts as
    (
        select
            period,
            project_id,
            project_name,
            month_num,
            month_name,
            planned_effort,
            actual_effort,
            _etl_date,
            _dlt_load_id
        from {{ ref('stg_shrp__operation_efforts') }}
    )
    ,
    with_calculations as
    (
        select
            period,
            cast(project_id as varchar) as project_id,
            project_name,
            month_num,
            month_name,
            planned_effort,
            actual_effort,
            -- Calculate variance in hours (actual - planned)
            case
                when planned_effort is not null and actual_effort is not null
                then actual_effort - planned_effort
                else null
            end as variance_hours,
            -- Calculate variance percentage ((actual - planned) / planned * 100)
            case
                when planned_effort is not null
                    and planned_effort != 0
                    and actual_effort is not null
                then ((actual_effort - planned_effort) / planned_effort) * 100
                else null
            end as variance_percent,
            -- Performance indicator flags
            case
                when planned_effort is null or actual_effort is null then 'Incomplete Data'
                when planned_effort = 0 then 'Incomplete Data'
                when actual_effort <= planned_effort then 'On Track'
                when (actual_effort - planned_effort) / planned_effort <= 0.1 then 'Slight Overrun'
                when (actual_effort - planned_effort) / planned_effort <= 0.2 then 'Moderate Overrun'
                else 'Significant Overrun'
            end as performance_indicator,
            _etl_date as etl_date,
            _dlt_load_id as dlt_load_id
        from staging_efforts
    )
    ,
    final as
    (
        select
            period,
            project_id,
            project_name,
            month_num,
            month_name,
            planned_effort,
            actual_effort,
            variance_hours,
            variance_percent,
            performance_indicator,
            etl_date,
            dlt_load_id
        from with_calculations
        where
            -- Only include rows where at least one effort value exists
            (planned_effort is not null or actual_effort is not null)
    )

select *
    ,current_timestamp as _etl_date
from final
order by period, project_id
