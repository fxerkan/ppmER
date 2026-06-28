{{
    config(
        materialized="view",
        schema="staging",
        tags=["sharepoint", "staging"],
        unique_key=["year", "project_id", "period"],
    )
}}

{#
  SharePoint CAPEX/OPEX Adjustment Staging Model

  This model unpivots the monthly CAPEX and OPEX ratio columns from the raw capex_opex_adjustment
  table into a long format with one row per project per month.

  Transforms from:
    year | project_id | ratio_jan_capex | ratio_jan_opex | ratio_feb_capex | ...

  To:
    year | project_id | period | ratio_capex | ratio_opex
    2025 | 10399      | 2025-01 | 0.80       | 0.20
    2025 | 10399      | 2025-02 | 0.75       | 0.25
    ...
#}

with
    source as (select * from {{ source("raw_sharepoint", "capex_opex_adjustment") }}),

    -- Unpivot the monthly columns into rows
    unpivoted as (
        -- January
        select
            year,
            project_id,
            project,
            cast(year as varchar) || '-01' as period,
            1 as month_num,
            'January' as month_name,
            ratio_jan_capex as ratio_capex,
            ratio_jan_opex as ratio_opex,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source

        union all

        -- February
        select
            year,
            project_id,
            project,
            cast(year as varchar) || '-02' as period,
            2 as month_num,
            'February' as month_name,
            ratio_feb_capex as ratio_capex,
            ratio_feb_opex as ratio_opex,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source

        union all

        -- March
        select
            year,
            project_id,
            project,
            cast(year as varchar) || '-03' as period,
            3 as month_num,
            'March' as month_name,
            ratio_mar_capex as ratio_capex,
            ratio_mar_opex as ratio_opex,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source

        union all

        -- April
        select
            year,
            project_id,
            project,
            cast(year as varchar) || '-04' as period,
            4 as month_num,
            'April' as month_name,
            ratio_apr_capex as ratio_capex,
            ratio_apr_opex as ratio_opex,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source

        union all

        -- May
        select
            year,
            project_id,
            project,
            cast(year as varchar) || '-05' as period,
            5 as month_num,
            'May' as month_name,
            ratio_may_capex as ratio_capex,
            ratio_may_opex as ratio_opex,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source

        union all

        -- June
        select
            year,
            project_id,
            project,
            cast(year as varchar) || '-06' as period,
            6 as month_num,
            'June' as month_name,
            ratio_jun_capex as ratio_capex,
            ratio_jun_opex as ratio_opex,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source

        union all

        -- July
        select
            year,
            project_id,
            project,
            cast(year as varchar) || '-07' as period,
            7 as month_num,
            'July' as month_name,
            ratio_jul_capex as ratio_capex,
            ratio_jul_opex as ratio_opex,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source

        union all

        -- August
        select
            year,
            project_id,
            project,
            cast(year as varchar) || '-08' as period,
            8 as month_num,
            'August' as month_name,
            ratio_aug_capex as ratio_capex,
            ratio_aug_opex as ratio_opex,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source

        union all

        -- September
        select
            year,
            project_id,
            project,
            cast(year as varchar) || '-09' as period,
            9 as month_num,
            'September' as month_name,
            ratio_sep_capex as ratio_capex,
            ratio_sep_opex as ratio_opex,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source

        union all

        -- October
        select
            year,
            project_id,
            project,
            cast(year as varchar) || '-10' as period,
            10 as month_num,
            'October' as month_name,
            ratio_oct_capex as ratio_capex,
            ratio_oct_opex as ratio_opex,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source

        union all

        -- November
        select
            year,
            project_id,
            project,
            cast(year as varchar) || '-11' as period,
            11 as month_num,
            'November' as month_name,
            ratio_nov_capex as ratio_capex,
            ratio_nov_opex as ratio_opex,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source

        union all

        -- December
        select
            year,
            project_id,
            project,
            cast(year as varchar) || '-12' as period,
            12 as month_num,
            'December' as month_name,
            ratio_dec_capex as ratio_capex,
            ratio_dec_opex as ratio_opex,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
    ),

    final as (
        select
            cast(year as bigint) as year,
            cast(project_id as bigint) as project_id,
            project,
            period,
            month_num,
            month_name,
            cast(ratio_capex as double precision) as ratio_capex,
            cast(ratio_opex as double precision) as ratio_opex,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from unpivoted
    )

select *
from final
order by year, project_id, month_num
