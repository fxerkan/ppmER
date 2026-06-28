{{
    config(
        materialized="view",
        schema="mart",
        tags=["error_check", "jira_data", "data_quality"]
    )
}}

/*
  ERROR CHECK: Issues without Project Assignment

  Description:
  Identifies Jira issues (Epic, Story, Task, etc.) that do not have a valid
  project assignment. This causes worklogs to be orphaned and unreportable.

  Expected Result:
  - Empty result = All issues have valid project assignments
  - Rows returned = Issues that need project assignment

  Impact:
  - Worklogs cannot be attributed to projects
  - Financial reporting incomplete
  - Distribution calculations fail

  Action Required:
  - Review Jira issues and assign to correct projects
  - Update stg_jira__issues with project mapping
*/

with issues_with_worklogs as (
    select distinct
        w.issue_id,
        w.issue_key,
        w.project_id as worklog_project_id,
        w.project_name as worklog_project_name,
        sum(w.time_spent_person_days) as total_effort
    from {{ ref('fact_worklogs') }} w
    where 1=1
        and w.period >= '2025-01'
    group by
        w.issue_id,
        w.issue_key,
        w.project_id,
        w.project_name
)

select
    i.issue_id,
    i.issue_key,
    i.issue_summary,
    i.issue_type_name,
    i.project_id as issue_project_id,
    i.project_key as issue_project_key,
    i.project_name as issue_project_name,
    w.worklog_project_id,
    w.worklog_project_name,
    round(w.total_effort, 2) as total_effort_person_days,
    case
        when i.project_id is null then 'Issue has no project_id'
        when i.project_id != w.worklog_project_id then 'Project mismatch between issue and worklogs'
        else 'Unknown error'
    end as error_type,
    'Assign issue to correct project in Jira' as recommended_action,
    current_timestamp as check_date
from {{ ref('dim_issues') }} i
inner join issues_with_worklogs w
    on i.issue_id = w.issue_id
where 1=1
    and (
        i.project_id is null
        or i.project_id != w.worklog_project_id
    )
order by w.total_effort desc
