{{ config(
    materialized="view",
    schema="mart",
    tags=["jira", "mart", "datamart"]
) }}

{#
  Financial Dashboard View - Enhanced with Manual Adjustments

  This view combines distributed efforts with manual adjustments from SharePoint.
  When a manual adjustment exists for a specific period + project_name combination,
  it overrides the calculated final_effort_adjusted value.

  Logic:
  - If adjustment_amount is NOT NULL and != 0: use adjustment_amount
  - Otherwise: use the original final_effort_adjusted from distributed efforts
#}



with
    fact_2025 as 
    (
        select *
        from {{ ref('fact_financial_dashboard_2025') }}
    )
    ,fact_2026 as 
    (
        select *
        from {{ ref('fact_financial_dashboard_2026') }}
    )
    ,unions as
    (
        select * from fact_2025
        union all select * from fact_2026
    )
select *
from unions