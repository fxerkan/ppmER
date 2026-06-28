{{
    config(
        materialized="table",
        schema="core",
        tags=["core", "dim", "reference"],
        unique_key="calendar_date",
    )
}}

{#
  Date Dimension Table

  Reference table for date-based analysis.
  Includes period closure flags for snapshot management.
  Generates dates from 2020 to 2030.
#}
with
    date_spine as (
        {{
            dbt_utils.date_spine(
                datepart="day",
                start_date="cast('2020-01-01' as date)",
                end_date="cast('2030-12-31' as date)",
            )
        }}
    )
    ,calc_period as (
        select
            period,
            period_start_date,
            period_end_date,
            is_locked
        from {{ ref("dim_calc_period") }}
    )

    ,turkish_holidays as (
        select
            holiday_date,
            holiday_name,
            holiday_type,
            expected_effort_person_days
        from {{ ref("dim_turkish_holidays") }}
    )

    ,final as (
        select
            -- Date values
            cast(date_day as date) as calendar_date,
            -- Primary key (YYYYMMDD format)
            cast(to_char(date_day, 'YYYYMMDD') as integer) as date_key,

            -- Year attributes
            extract(year from date_day) as year,
            extract(quarter from date_day) as quarter,
            extract(month from date_day) as month,
            extract(week from date_day) as week_of_year,
            extract(day from date_day) as day_of_month,
            extract(dow from date_day) as day_of_week,
            extract(doy from date_day) as day_of_year,

            -- Period keys for joining
            to_char(date_day, 'YYYY-MM') as year_month,
            to_char(date_day, 'YYYY')
            || '-Q'
            || extract(quarter from date_day) as year_quarter,

            -- Date truncations
            date_trunc('week', date_day)::date as week_start_date,
            (date_trunc('week', date_day) + interval '6 days')::date as week_end_date,
            date_trunc('month', date_day)::date as month_start_date,
            (
                date_trunc('month', date_day) + interval '1 month' - interval '1 day'
            )::date as month_end_date,
            date_trunc('quarter', date_day)::date as quarter_start_date,
            (
                date_trunc('quarter', date_day) + interval '3 months' - interval '1 day'
            )::date as quarter_end_date,
            date_trunc('year', date_day)::date as year_start_date,
            (date_trunc('year', date_day) + interval '1 year' - interval '1 day')::date
            as year_end_date,

            -- Name attributes
            to_char(date_day, 'Day') as day_name,
            to_char(date_day, 'Dy') as day_name_short,
            to_char(date_day, 'Month') as month_name,
            to_char(date_day, 'Mon') as month_name_short,

            -- Flags
            case
                when extract(dow from date_day) in (0, 6) then true else false
            end as is_weekend,
            case
                when extract(dow from date_day) not in (0, 6) then true else false
            end as is_weekday,

            -- Period closure flags (for snapshot management)
            -- A month is closed if it's before the current month
            cp.is_locked as is_period_locked,

            -- Working effort calculation
            -- Expected person-days of effort for this date
            -- Defaults to 1.0 for regular weekdays, 0.0 for weekends, or uses holiday value if exists
            coalesce(
                th.expected_effort_person_days,
                case
                    when extract(dow from date_day) in (0, 6) then 0.0  -- Weekend: 0 effort
                    else 1.0  -- Weekday: 1 person-day (8 hours)
                end
            ) as expected_effort_person_days,
            th.holiday_name,
            th.holiday_type,
            {# case
                when date_trunc('month', date_day) < date_trunc('month', current_date)
                then true
                else false
            end as is_month_closed,

            -- A quarter is closed if it's before the current quarter
            case
                when
                    date_trunc('quarter', date_day)
                    < date_trunc('quarter', current_date)
                then true
                else false
            end as is_quarter_closed,

            -- A year is closed if it's before the current year
            case
                when date_trunc('year', date_day) < date_trunc('year', current_date)
                then true
                else false
            end as is_year_closed, #}

            -- Relative date flags
            case when date_day = current_date then true else false end as is_today,
            case
                when date_day = current_date - interval '1 day' then true else false
            end as is_yesterday,
            case
                when
                    date_day >= date_trunc('week', current_date)
                    and date_day < date_trunc('week', current_date) + interval '7 days'
                then true
                else false
            end as is_current_week,
            case
                when
                    date_day >= date_trunc('month', current_date)
                    and date_day
                    < date_trunc('month', current_date) + interval '1 month'
                then true
                else false
            end as is_current_month,
            case
                when
                    date_day >= date_trunc('quarter', current_date)
                    and date_day
                    < date_trunc('quarter', current_date) + interval '3 months'
                then true
                else false
            end as is_current_quarter,
            case
                when
                    date_day >= date_trunc('year', current_date)
                    and date_day < date_trunc('year', current_date) + interval '1 year'
                then true
                else false
            end as is_current_year,
            current_timestamp as _etl_date
        from date_spine ds
        left join calc_period cp
            on ds.date_day between cp.period_start_date and cp.period_end_date
        left join turkish_holidays th
            on ds.date_day = th.holiday_date
    )

select *
from final
where 1=1
and calendar_date < date_trunc('month',current_date) +  interval '1 month'
