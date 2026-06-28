{{
    config(
        materialized="view",
        schema="mart",
        tags=["error_check", "transactional_data", "data_quality"]
    )
}}

/*
  ERROR CHECK: fact_worklogs - Negative Time Values

  Description:
  Identifies worklogs with negative time_spent values, which are invalid.
  Negative values indicate data quality issues in Jira or ETL process.

  Expected Result:
  - Empty result = No negative values found
  - Rows returned = Invalid worklogs that need correction

  Impact:
  - Incorrect effort calculations
  - Negative values in financial reports
  - Distribution calculation errors

  Action Required:
  - Review Jira source data
  - Correct or exclude invalid worklogs
  - Investigate ETL transformation logic
*/

select
    worklog_id,
    period,
    trx_date,
    issue_id,
    issue_key,
    project_id,
    project_name,
    author_name,
    author_email,
    time_spent_display,
    time_spent_seconds,
    time_spent_hours,
    time_spent_person_days,
    work_started_date,
    created_date,
    updated_date,
    'Negative time_spent_seconds' as error_type,
    'Review and correct Jira worklog entry' as recommended_action,
    _etl_date as check_date
from {{ ref('fact_worklogs') }}
where 1=1
    and (
        time_spent_seconds < 0
        or time_spent_hours < 0
        or time_spent_person_days < 0
    )
order by
    trx_date desc,
    time_spent_seconds asc
