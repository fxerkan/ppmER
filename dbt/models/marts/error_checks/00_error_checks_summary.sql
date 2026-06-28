{{
    config(
        materialized="view",
        schema="mart",
        tags=["error_check", "summary", "data_quality"]
    )
}}

/*
  ERROR CHECKS SUMMARY

  Description:
  Provides a high-level summary of all data quality error checks.
  Shows which checks have errors and how many errors were found.

  Usage:
  - Run this view first to get an overview of data quality issues
  - Use error_count to prioritize which detailed checks to investigate
  - Empty result = All data quality checks passed

  Categories:
  1. Master Data - Dimension table quality
  2. Transactional Data - Fact table quality
  3. Row Count Checks - Data completeness
  4. SharePoint Data - Manual data quality
  5. Jira Data - Source system data quality
  6. Data Quality - Freshness and general quality

  Action Required:
  Investigate detailed error check views for categories with error_count > 0
*/

with master_data_errors as (
    select
        'Master Data' as category,
        'dim_projects_missing_data' as check_name,
        count(*) as error_count,
        'Critical' as severity
    from {{ ref('01_dim_projects_missing_data') }}
    where 1=1

    union all

    select
        'Master Data' as category,
        'dim_projects_duplicate_keys' as check_name,
        count(*) as error_count,
        'Critical' as severity
    from {{ ref('02_dim_projects_duplicate_keys') }}
    where 1=1
),

sharepoint_errors as (
    select
        'SharePoint Data' as category,
        'projects_not_in_master' as check_name,
        count(*) as error_count,
        'High' as severity
    from {{ ref('01_projects_not_in_master') }}
    where 1=1
),

transactional_errors as (
    select
        'Transactional Data' as category,
        'fact_worklogs_negative_values' as check_name,
        count(*) as error_count,
        'Critical' as severity
    from {{ ref('01_fact_worklogs_negative_values') }}
    where 1=1

    union all

    select
        'Transactional Data' as category,
        'distributed_efforts_calculation' as check_name,
        count(*) as error_count,
        'High' as severity
    from {{ ref('02_distributed_efforts_calculation_validation') }}
    where 1=1
),

row_count_errors as (
    select
        'Row Count Checks' as category,
        'worklogs_row_count_validation' as check_name,
        count(*) as error_count,
        'Critical' as severity
    from {{ ref('01_worklogs_row_count_validation') }}
    where 1=1
),

jira_errors as (
    select
        'Jira Data' as category,
        'issues_without_project' as check_name,
        count(*) as error_count,
        'High' as severity
    from {{ ref('01_issues_without_project') }}
    where 1=1
),

freshness_errors as (
    select
        'Data Quality' as category,
        'financial_dashboard_freshness' as check_name,
        count(*) as error_count,
        severity
    from {{ ref('01_financial_dashboard_data_freshness') }}
    where 1=1
),

all_checks as (
    select * from master_data_errors
    union all
    select * from sharepoint_errors
    union all
    select * from transactional_errors
    union all
    select * from row_count_errors
    union all
    select * from jira_errors
    union all
    select * from freshness_errors
)

select
    category,
    check_name,
    error_count,
    severity,
    case
        when error_count = 0 then 'PASS'
        when error_count > 0 and severity = 'Critical' then 'FAIL - CRITICAL'
        when error_count > 0 and severity = 'High' then 'FAIL - HIGH'
        else 'FAIL - WARNING'
    end as status,
    current_timestamp as check_date
from all_checks
where error_count > 0  -- Only show failed checks
order by
    case severity
        when 'Critical' then 1
        when 'High' then 2
        when 'Warning' then 3
        else 4
    end,
    error_count desc
