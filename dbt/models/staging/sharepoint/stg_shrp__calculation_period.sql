{{
    config(
        materialized="view",
        schema="staging",
        tags=["sharepoint", "staging"],
    )
}}

{#
  SharePoint Calculation Period Staging Model

  Master data for Calculation Period.
#}

with
    source as (select * from {{ source("raw_sharepoint", "calculation_period") }})

    ,renamed as (
        select
            cast(field_0 as varchar) as period,
            title as period_name,
            cast(case when field_2 = 'Evet' then 1 else 0 end as boolean) as is_locked,
            cast(field_3 as timestamp) as lock_date,
            cast(field_0 || '-01' as date) as period_start_date,
            cast( ((cast(field_0 || '-01' as date) + INTERVAL '1 MONTH') - INTERVAL '1 DAY') as date) as period_end_date,
            _etl_date
            --_dlt_load_id,
            --_dlt_id
        from source
    )
select
    *
from renamed
