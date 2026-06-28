{{
    config(
        materialized="table",
        schema="core",
        tags=["core", "dim", "reference"],
        unique_key="period",
    )
}}

{#
  Calculation Period Dimension Table
    Reference table for calculation periods used in Jira data processing.
#}
with
    --base as ( select * from {{ ref("stg_manual__calc_period") }} ),
    base as ( select * from {{ ref("stg_shrp__calculation_period") }} ),

    final as (
        select
            period,
            period_name,
            is_locked,
            lock_date,
            period_start_date,
            period_end_date,
            current_timestamp as _etl_date
        from base
    )
select *
from final
where 1=1
and period_start_date < date_trunc('month',current_date) +  interval '1 month'