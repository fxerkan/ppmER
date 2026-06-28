{{
    config(
        materialized="view",
        schema="staging",
        tags=["jira", "manual", "staging"],
        unique_key="period",
    )
}}

with
    source as (select * from {{ source("raw_manual", "calc_period") }})

    ,renamed as (
        select
            cast(period as varchar) as period,
            period_name,
            cast(is_locked as boolean) as is_locked,
            cast(lock_date as timestamp) as lock_date,
            cast(period || '-01' as date) as period_start_date,
            cast( ((cast(period || '-01' as date) + INTERVAL '1 MONTH') - INTERVAL '1 DAY') as date) as period_end_date,
            _etl_date
            --_dlt_load_id,
            --_dlt_id
        from source
    )
select
    *
from renamed
