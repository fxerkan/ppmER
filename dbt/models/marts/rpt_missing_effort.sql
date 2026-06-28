{{
    config(
        materialized="table",
        schema="mart",
        tags=["jira", "mart", "report", "missing_effort"]
    )
}}

{#
  Missing Effort Report

  This report identifies missing effort entries by comparing:
  - Expected working effort (from dim_calendar with Turkish holidays)
  - Actual logged effort (from fact_worklogs)

  Key Metrics:
  - Total Expected Effort: Sum of expected person-days from calendar
  - Total Actual Effort: Sum of time_spent_person_days from worklogs
  - Total Missing Effort: Expected - Actual (only positive values shown)
  - Timesheet Entry %: (Actual / Expected) * 100

  Dimensions:
  - Period (YYYY-MM)
  - Date Range (start_date, end_date)
  - Employee (author_name, author_full_name, author_email)
  - Unit/Team (author_unit, author_team, deputy_gm_upper_unit, unit_name)
  - Tribe, Project, Manager

  Usage:
  - Shows ONLY missing effort (excludes equal or excess effort entries)
  - Filterable by all dimensions for detailed analysis
  - Daily breakdown available via trx_date
#}

with
    -- Get all working days with expected effort
    calendar as (
        select
            calendar_date,
            year_month as period,
            year,
            month,
            day_name,
            is_weekend,
            expected_effort_person_days,
            holiday_name,
            holiday_type
        from {{ ref('dim_calendar') }}
        where 1=1
            and calendar_date >= '2025-01-01'
            and calendar_date < '2027-01-01'
    ),

    -- Get all employees from worklogs (distinct users who logged time)
    employees as (
        select distinct
            author_id,
            author_name,
            author_full_name,
            author_email,
            author_unit,
            author_team,
            deputy_gm_upper_unit,
            unit_name,
            is_outsource_inhouse,
            exit_date
        from {{ ref('fact_worklogs') }}
        where 1=1
            and trx_date >= '2025-01-01'
            and trx_date < '2027-01-01'
    ),

    -- Create employee-day combinations (expected effort for each employee per day)
    expected_effort_base as (
        select
            c.calendar_date as trx_date,
            c.period,
            c.year,
            c.month,
            c.day_name,
            c.is_weekend,
            c.expected_effort_person_days,
            c.holiday_name,
            c.holiday_type,
            e.author_id,
            e.author_name,
            e.author_full_name,
            e.author_email,
            e.author_unit,
            e.author_team,
            e.deputy_gm_upper_unit,
            e.unit_name,
            e.is_outsource_inhouse,
            e.exit_date
        from calendar c
        cross join employees e
    ),

    -- Get actual effort logged by employees
    actual_effort as (
        select
            trx_date,
            period,
            author_id,
            author_name,
            author_full_name,
            author_email,
            author_unit,
            author_team,
            deputy_gm_upper_unit,
            unit_name,
            is_outsource_inhouse,
            tribe,
            project_id,
            project_name,
            sum(time_spent_person_days) as total_actual_effort
        from {{ ref('fact_worklogs') }}
        where 1=1
            and trx_date >= '2025-01-01'
            and trx_date < '2027-01-01'
        group by
            trx_date,
            period,
            author_id,
            author_name,
            author_full_name,
            author_email,
            author_unit,
            author_team,
            deputy_gm_upper_unit,
            unit_name,
            is_outsource_inhouse,
            tribe,
            project_id,
            project_name
    ),

    -- Daily employee effort comparison
    daily_effort_comparison as (
        select
            exp.trx_date,
            exp.period,
            exp.year,
            exp.month,
            exp.day_name,
            exp.is_weekend,
            exp.expected_effort_person_days,
            exp.holiday_name,
            exp.holiday_type,
            exp.author_id,
            exp.author_name,
            exp.author_full_name,
            exp.author_email,
            exp.author_unit,
            exp.author_team,
            exp.deputy_gm_upper_unit,
            exp.unit_name,
            exp.is_outsource_inhouse,
            exp.exit_date,
            coalesce(sum(act.total_actual_effort), 0) as total_actual_effort_day
        from expected_effort_base exp
        left join actual_effort act
            on exp.trx_date = act.trx_date
            and exp.author_id = act.author_id
        group by
            exp.trx_date,
            exp.period,
            exp.year,
            exp.month,
            exp.day_name,
            exp.is_weekend,
            exp.expected_effort_person_days,
            exp.holiday_name,
            exp.holiday_type,
            exp.author_id,
            exp.author_name,
            exp.author_full_name,
            exp.author_email,
            exp.author_unit,
            exp.author_team,
            exp.deputy_gm_upper_unit,
            exp.unit_name,
            exp.is_outsource_inhouse,
            exp.exit_date
    ),

    -- Calculate missing effort (only where actual < expected)
    missing_effort_daily as (
        select
            trx_date,
            period,
            year,
            month,
            day_name,
            is_weekend,
            expected_effort_person_days,
            holiday_name,
            holiday_type,
            author_id,
            author_name,
            author_full_name,
            author_email,
            author_unit,
            author_team,
            deputy_gm_upper_unit,
            unit_name,
            is_outsource_inhouse,
            exit_date,
            total_actual_effort_day,
            expected_effort_person_days - total_actual_effort_day as missing_effort_person_days,
            case
                when expected_effort_person_days > 0
                then round((total_actual_effort_day / expected_effort_person_days) * 100, 2)
                else 0
            end as timesheet_entry_percentage
        from daily_effort_comparison
        where 1=1
            -- Only show missing effort (actual < expected)
            and total_actual_effort_day < expected_effort_person_days
            -- Exclude days with 0 expected effort (full holidays and weekends)
            and expected_effort_person_days > 0
    )
    select *
    from missing_effort_daily
    where 1=1
    and trx_date <= current_date
    -- Exclude missing effort after employee exit date
    and (exit_date is null or trx_date <= exit_date)
    ----and author_name = 'İlhan Yiğit'
    and timesheet_entry_percentage < 100
    