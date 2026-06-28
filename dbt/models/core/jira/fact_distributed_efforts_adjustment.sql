{{
    config(
        materialized="table",
        schema="mart",
        tags=["sharepoint", "core", "fact", "adjustment"],
        unique_key=["period", "project_id"]
    )
}}

{#
  Financial Adjustment Mart Model

  This model brings the financial adjustments from staging to the mart layer,
  providing period-based adjustments for projects that override the calculated
  distributed efforts.

  Key columns:
  - period: YYYY-MM format (e.g., '2025-01')
  - project_id: Jira project ID
  - adjustment_amount: The manual adjustment value entered by power users
  - project_name: Project name for reference

  Usage:
  This table is joined with fact_distributed_efforts_view in financial_dashboard_view
  to apply manual adjustments when they exist, falling back to calculated values otherwise.
#}

with
    staging_adjustments as 
    (
        select
            period,
            project_id,
            project_name,
            month_num,
            month_name,
            adjustment_amount,
            _etl_date,
            _dlt_load_id
        from {{ ref('stg_shrp__financial_adjustment') }}
    )
    ,final as 
    (
        select
            period,
            cast(project_id as varchar) as project_id,
            project_name,
            month_num,
            month_name,
            adjustment_amount,
            _etl_date as etl_date,
            _dlt_load_id as dlt_load_id
        from staging_adjustments
        where adjustment_amount is not null
            and adjustment_amount != 0
    )
select *
    ,current_timestamp as _etl_date
from final
order by period, project_id
