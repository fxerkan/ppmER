{{ 
    config(
        materialized="table", 
        schema="mart", 
        tags=["jira", "mart", "datamart"],
        enabled=false,
        ) 
}}

{#
  Portfolio Dashboard Mart

  Executive-level portfolio view combining project dimensions
  with aggregated metrics for dashboard consumption.
#}
with
    projects as (select * from {{ ref("dim_projects") }}),

    portfolio_summary as (
        select
            -- Project identifiers
            project_id,
            project_key,
            project_name,
            project_type,
            project_description,
            is_private,

            -- Portfolio attributes
            business_line,
            customer,
            product,
            product_group,
            tribe,
            it_domain,
            hosting,
            open_closed,

            -- Project health indicator
            case
                when completion_pct >= 80
                then 'On Track'
                when completion_pct >= 50
                then 'At Risk'
                else 'Behind Schedule'
            end as project_health,

            -- Issue metrics
            total_issues,
            completed_issues,
            in_progress_issues,
            todo_issues,
            completion_pct,

            -- Resource metrics
            total_hours_logged,
            total_worklogs,
            unique_assignees,
            unique_reporters,

            -- Calculated metrics
            case
                when completed_issues > 0
                then round(total_hours_logged / completed_issues, 2)
                else null
            end as avg_hours_per_completed_issue,

            case
                when total_issues > 0
                then round(total_hours_logged / total_issues, 2)
                else null
            end as avg_hours_per_issue,

            -- Dates
            first_issue_created_date,
            last_issue_updated_date,

            -- Metadata
            dbt_updated_date,
            current_timestamp as _etl_date
        from projects
    )

select *
from portfolio_summary
order by project_name
