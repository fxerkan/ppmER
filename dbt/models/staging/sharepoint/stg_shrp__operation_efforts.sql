{{
    config(
        materialized="view",
        schema="staging",
        tags=["sharepoint", "staging"],
        unique_key=["year", "project_id", "period"],
    )
}}

{#
  SharePoint Operation Efforts Staging Model

  This model unpivots the monthly planned and actual effort columns from the raw operation_efforts
  table into a long format with one row per project per month, with separate columns for planned
  and actual values.

  Transforms from:
    year | project_id | jan_planned | jan_actual | feb_planned | feb_actual | ...

  To:
    year | project_id | period | planned_effort | actual_effort
    2025 | 10399      | 2025-01 | 150.5 | 145.2
    2025 | 10399      | 2025-02 | 160.0 | 158.3
    ...
#}

with
    source as (select * from {{ source("raw_sharepoint", "operation_efforts") }}),

    -- Unpivot the monthly columns into rows, combining planned and actual for each month
    unpivoted as (
        -- January
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-01' as period,
            1 as month_num,
            'January' as month_name,
            jan_planned as planned_effort,
            jan_actual as actual_effort,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where jan_planned is not null or jan_actual is not null

        union all

        -- February
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-02' as period,
            2 as month_num,
            'February' as month_name,
            feb_planned as planned_effort,
            feb_actual as actual_effort,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where feb_planned is not null or feb_actual is not null

        union all

        -- March
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-03' as period,
            3 as month_num,
            'March' as month_name,
            mar_planned as planned_effort,
            mar_actual as actual_effort,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where mar_planned is not null or mar_actual is not null

        union all

        -- April
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-04' as period,
            4 as month_num,
            'April' as month_name,
            apr_planned as planned_effort,
            apr_actual as actual_effort,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where apr_planned is not null or apr_actual is not null

        union all

        -- May
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-05' as period,
            5 as month_num,
            'May' as month_name,
            may_planned as planned_effort,
            may_actual as actual_effort,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where may_planned is not null or may_actual is not null

        union all

        -- June
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-06' as period,
            6 as month_num,
            'June' as month_name,
            jun_planned as planned_effort,
            jun_actual as actual_effort,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where jun_planned is not null or jun_actual is not null

        union all

        -- July
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-07' as period,
            7 as month_num,
            'July' as month_name,
            jul_planned as planned_effort,
            jul_actual as actual_effort,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where jul_planned is not null or jul_actual is not null

        union all

        -- August
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-08' as period,
            8 as month_num,
            'August' as month_name,
            aug_planned as planned_effort,
            aug_actual as actual_effort,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where aug_planned is not null or aug_actual is not null

        union all

        -- September
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-09' as period,
            9 as month_num,
            'September' as month_name,
            sep_planned as planned_effort,
            sep_actual as actual_effort,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where sep_planned is not null or sep_actual is not null

        union all

        -- October
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-10' as period,
            10 as month_num,
            'October' as month_name,
            oct_planned as planned_effort,
            oct_actual as actual_effort,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where oct_planned is not null or oct_actual is not null

        union all

        -- November
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-11' as period,
            11 as month_num,
            'November' as month_name,
            nov_planned as planned_effort,
            nov_actual as actual_effort,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where nov_planned is not null or nov_actual is not null

        union all

        -- December
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-12' as period,
            12 as month_num,
            'December' as month_name,
            dec_planned as planned_effort,
            dec_actual as actual_effort,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where dec_planned is not null or dec_actual is not null
    ),

    final as (
        select
            cast(year as bigint) as year,
            cast(project_id as bigint) as project_id,
            project_name,
            period,
            month_num,
            month_name,
            cast(planned_effort as double precision) as planned_effort,
            cast(actual_effort as double precision) as actual_effort,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from unpivoted
    )

select *
from final
order by year, project_id, month_num
