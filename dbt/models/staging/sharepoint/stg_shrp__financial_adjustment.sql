{{
    config(
        materialized="view",
        schema="staging",
        tags=["sharepoint", "staging"],
        unique_key=["year", "project_id", "period"],
    )
}}

{#
  SharePoint Financial Adjustment Staging Model

  This model unpivots the monthly adjustment columns from the raw financial_adjustment
  table into a long format with one row per project per month.

#}

with
    source as (select * from {{ source("raw_sharepoint", "financial_adjustment") }}),

    -- Unpivot the monthly columns into rows
    unpivoted as (
        -- January
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-01' as period,
            1 as month_num,
            'January' as month_name,
            jan_uary_adjusted as adjustment_amount,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where jan_uary_adjusted is not null

        union all

        -- February
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-02' as period,
            2 as month_num,
            'February' as month_name,
            february_adjusted as adjustment_amount,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where february_adjusted is not null

        union all

        -- March
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-03' as period,
            3 as month_num,
            'March' as month_name,
            march_adjusted as adjustment_amount,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where march_adjusted is not null

        union all

        -- April
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-04' as period,
            4 as month_num,
            'April' as month_name,
            april_adjusted as adjustment_amount,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where april_adjusted is not null

        union all

        -- May
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-05' as period,
            5 as month_num,
            'May' as month_name,
            may_adjusted as adjustment_amount,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where may_adjusted is not null

        union all

        -- June
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-06' as period,
            6 as month_num,
            'June' as month_name,
            june_adjusted as adjustment_amount,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where june_adjusted is not null

        union all

        -- July
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-07' as period,
            7 as month_num,
            'July' as month_name,
            july_adjusted as adjustment_amount,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where july_adjusted is not null

        union all

        -- August
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-08' as period,
            8 as month_num,
            'August' as month_name,
            august_adjusted as adjustment_amount,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where august_adjusted is not null

        union all

        -- September
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-09' as period,
            9 as month_num,
            'September' as month_name,
            september_adjusted as adjustment_amount,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where september_adjusted is not null

        union all

        -- October
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-10' as period,
            10 as month_num,
            'October' as month_name,
            october_adjusted as adjustment_amount,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where october_adjusted is not null

        union all

        -- November
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-11' as period,
            11 as month_num,
            'November' as month_name,
            november_adjusted as adjustment_amount,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where november_adjusted is not null

        union all

        -- December
        select
            year,
            project_id,
            project_name,
            cast(year as varchar) || '-12' as period,
            12 as month_num,
            'December' as month_name,
            december_adjusted as adjustment_amount,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from source
        where december_adjusted is not null
    ),

    final as (
        select
            cast(year as bigint) as year,
            cast(project_id as bigint) as project_id,
            project_name,
            period,
            month_num,
            month_name,
            cast(adjustment_amount as double precision) as adjustment_amount,
            _etl_date,
            _dlt_load_id,
            _dlt_id
        from unpivoted
        -- Filter out records with NULL year (critical field)
        -- Allow NULL project_id as per business requirements
        where year is not null
    )

select *
from final
order by year, project_id, month_num
