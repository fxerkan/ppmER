{{
    config(
        materialized="view",
        schema="mart",
        tags=["error_check", "sharepoint_data", "data_quality"]
    )
}}

/*
  ERROR CHECK: Projects with Effort but NOT in dim_projects Master Data

  Description:
  Identifies projects that have logged effort in fact_worklogs but do not exist
  in dim_projects master data. This indicates missing project setup or data sync issues.

  Expected Result:
  - Empty result = All projects with effort exist in master data
  - Rows returned = Projects that need to be added to dim_projects

  Impact:
  - Missing projects will show as NULL in reports
  - Financial codes and distribution settings cannot be applied
  - Dashboard reports will be incomplete

  Action Required:
  - Add missing projects to Jira or SharePoint project master data
  - Verify project_id mapping between Jira and master data
*/

with projects_with_effort as (
    select distinct
        w.project_id,
        w.project_key,
        w.project_name,
        w.period,
        sum(w.time_spent_person_days) as total_effort
    from {{ ref('fact_worklogs') }} w
    where 1=1
        and w.period >= '2025-01'
    group by
        w.project_id,
        w.project_key,
        w.project_name,
        w.period
),

master_projects as (
    select distinct
        project_id,
        project_key,
        project_name
    from {{ ref('dim_projects') }}
)

select
    e.period,
    e.project_id,
    e.project_key,
    e.project_name,
    round(e.total_effort, 2) as total_effort_person_days,
    round(e.total_effort * 8, 2) as total_effort_hours,
    'Missing in dim_projects' as error_type,
    'Add project to master data' as recommended_action,
    current_timestamp as check_date
from projects_with_effort e
left join master_projects m
    on e.project_id = m.project_id
where m.project_id is null
order by
    e.period desc,
    e.total_effort desc
