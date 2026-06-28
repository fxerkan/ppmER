{{
    config(
        materialized="view",
        schema="mart",
        tags=["error_check", "data_quality", "freshness"]
    )
}}

/*
  ERROR CHECK: Financial Dashboard Data Freshness

  Description:
  Checks the freshness of data in financial_dashboard_view and underlying tables.
  Identifies stale data that may indicate ETL failures.

  Expected Result:
  - Empty result = All data is fresh (within acceptable thresholds)
  - Rows returned = Stale data sources that need investigation

  Freshness Thresholds:
  - fact_worklogs: Should be updated daily (max 2 days old)
  - dim_projects: Should be updated weekly (max 7 days old)
  - financial_dashboard_view: Should be refreshed daily (max 2 days old)

  Impact:
  - Stale data leads to outdated reports
  - Missing recent worklogs
  - Incorrect financial metrics

  Action Required:
  - Check ETL job logs for failures
  - Verify source system connectivity
  - Re-run failed dbt models
*/

with data_freshness as (
    select
        'fact_worklogs' as table_name,
        max(trx_date) as last_transaction_date,
        max(_etl_date) as last_etl_date,
        current_date - max(trx_date) as days_since_last_transaction,
        current_timestamp - max(_etl_date) as time_since_last_etl,
        2 as freshness_threshold_days,
        'Critical - Daily refresh expected' as severity
    from {{ ref('fact_worklogs') }}

    union all

    select
        'dim_projects' as table_name,
        null as last_transaction_date,
        max(_etl_date) as last_etl_date,
        null as days_since_last_transaction,
        current_timestamp - max(_etl_date) as time_since_last_etl,
        7 as freshness_threshold_days,
        'Warning - Weekly refresh expected' as severity
    from {{ ref('dim_projects') }}

    union all

    select
        'dim_issues' as table_name,
        null as last_transaction_date,
        max(_etl_date) as last_etl_date,
        null as days_since_last_transaction,
        current_timestamp - max(_etl_date) as time_since_last_etl,
        2 as freshness_threshold_days,
        'Critical - Daily refresh expected' as severity
    from {{ ref('dim_issues') }}

    union all

    select
        'fact_distributed_efforts_2026' as table_name,
        max(period::date) as last_transaction_date,
        current_timestamp as last_etl_date,
        current_date - max(period::date) as days_since_last_transaction,
        interval '0' as time_since_last_etl,
        31 as freshness_threshold_days,
        'Warning - Monthly refresh expected' as severity
    from {{ ref('fact_distributed_efforts_2026') }}
)

select
    table_name,
    last_transaction_date,
    last_etl_date,
    days_since_last_transaction,
    extract(epoch from time_since_last_etl) / 86400 as days_since_last_etl,
    freshness_threshold_days,
    severity,
    case
        when days_since_last_transaction > freshness_threshold_days then 'STALE DATA - Transaction Date'
        when extract(epoch from time_since_last_etl) / 86400 > freshness_threshold_days then 'STALE DATA - ETL Date'
        else null
    end as error_type,
    'Check ETL job logs and re-run if necessary' as recommended_action,
    current_timestamp as check_date
from data_freshness
where 1=1
    and (
        days_since_last_transaction > freshness_threshold_days
        or extract(epoch from time_since_last_etl) / 86400 > freshness_threshold_days
    )
order by severity, days_since_last_etl desc
