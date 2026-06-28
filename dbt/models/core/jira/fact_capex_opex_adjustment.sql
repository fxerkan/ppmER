{{
    config(
        materialized="table",
        schema="mart",
        tags=["sharepoint", "core", "fact", "adjustment"],
        unique_key=["period", "project_id"]
    )
}}

{#
  CAPEX/OPEX Adjustment Mart Model

  This model brings the CAPEX/OPEX ratio adjustments from staging to the mart layer,
  providing period-based ratio adjustments for projects.

  Key columns:
  - period: YYYY-MM format (e.g., '2025-01')
  - project_id: Jira project ID
  - ratio_capex: The CAPEX ratio entered by power users
  - ratio_opex: The OPEX ratio entered by power users
  - project_name: Project name for reference

  Usage:
  This table is joined with financial models to apply manual CAPEX/OPEX ratio
  adjustments when they exist.
#}

with
    staging_adjustments as
    (
        select
            period,
            project_id,
            project as project_name,
            month_num,
            month_name,
            ratio_capex,
            ratio_opex,
            _etl_date,
            _dlt_load_id
        from {{ ref('stg_shrp__capex_opex_adjustment') }}
    )
    ,final as
    (
        select
            period,
            cast(project_id as varchar) as project_id,
            project_name,
            month_num,
            month_name,
            ratio_capex,
            ratio_opex,
            _etl_date as etl_date,
            _dlt_load_id as dlt_load_id
        from staging_adjustments
        where ratio_capex is not null
            or ratio_opex is not null
    )
select *
    ,current_timestamp as _etl_date
from final
order by period, project_id
