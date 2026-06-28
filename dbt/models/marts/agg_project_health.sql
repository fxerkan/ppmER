{{
    config(
        materialized="table",
        schema="mart",
        tags=["jira", "mart", "datamart", "aggregate"],
        enabled=false,
    )
}}

{#
  Project Health Aggregate Mart

  Aggregated project health metrics for executive dashboards.
  Combines issue, worklog, and relationship data for comprehensive
  project health scoring.
#}
with
    issues as (select * from {{ ref("fact_issues") }}),

    projects as (select * from {{ ref("dim_projects") }}),

    project_metrics as (
        select
            project_key,
            project_name,

            -- Volume metrics
            count(*) as total_issues,
            count(distinct assignee_id) as unique_assignees,
            count(distinct reporter_id) as unique_reporters,

            -- Status distribution
            sum(case when status_category = 'Done' then 1 else 0 end) as done_issues,
            sum(
                case when status_category = 'In Progress' then 1 else 0 end
            ) as in_progress_issues,
            sum(case when status_category = 'To Do' then 1 else 0 end) as todo_issues,

            -- Type distribution
            sum(case when issue_type = 'Bug' then 1 else 0 end) as bug_count,
            sum(case when issue_type = 'Story' then 1 else 0 end) as story_count,
            sum(case when issue_type = 'Task' then 1 else 0 end) as task_count,
            sum(case when issue_type = 'Epic' then 1 else 0 end) as epic_count,

            -- Priority distribution
            sum(case when priority = 'Highest' then 1 else 0 end) as highest_priority,
            sum(case when priority = 'High' then 1 else 0 end) as high_priority,
            sum(case when priority = 'Medium' then 1 else 0 end) as medium_priority,
            sum(case when priority = 'Low' then 1 else 0 end) as low_priority,
            sum(case when priority = 'Lowest' then 1 else 0 end) as lowest_priority,

            -- Relationship metrics
            sum(total_issue_links) as total_links,
            sum(blocks_count) as total_blocks,
            sum(total_subtasks) as total_subtasks,
            sum(completed_subtasks) as completed_subtasks,

            -- Time metrics
            avg(age_days) as avg_issue_age_days,
            max(age_days) as oldest_issue_age_days,
            min(created_date) as first_issue_created_date,
            max(created_date) as last_issue_created_date,
            max(updated_date) as last_issue_updated_date,

            -- Worklog metrics
            sum(total_hours_logged) as total_hours_logged

        from issues
        group by project_key, project_name
    ),

    final as (
        select
            p.project_id,
            m.project_key,
            m.project_name,
            p.project_type,
            p.is_private,

            -- Portfolio attributes
            p.business_line,
            p.customer,
            p.product,
            p.tribe,

            -- Volume metrics
            m.total_issues,
            m.unique_assignees,
            m.unique_reporters,

            -- Completion metrics
            m.done_issues,
            m.in_progress_issues,
            m.todo_issues,
            round(
                m.done_issues::numeric / nullif(m.total_issues, 0) * 100, 2
            ) as completion_pct,

            -- Type distribution
            m.bug_count,
            m.story_count,
            m.task_count,
            m.epic_count,

            -- Priority distribution
            m.highest_priority,
            m.high_priority,
            m.medium_priority,
            m.low_priority,
            m.lowest_priority,

            -- Relationship metrics
            m.total_links,
            m.total_blocks,
            m.total_subtasks,
            m.completed_subtasks,
            case
                when m.total_subtasks > 0
                then round(m.completed_subtasks::numeric / m.total_subtasks * 100, 2)
                else null
            end as subtask_completion_pct,

            -- Time metrics
            round(m.avg_issue_age_days::numeric, 2) as avg_issue_age_days,
            round(m.oldest_issue_age_days::numeric, 2) as oldest_issue_age_days,
            m.first_issue_created_date,
            m.last_issue_created_date,
            m.last_issue_updated_date,

            -- Worklog metrics
            round(m.total_hours_logged::numeric, 2) as total_hours_logged,

            -- Health score (0-100 based on completion and age)
            case
                when m.total_issues = 0
                then null
                else
                    round(
                        (
                            (m.done_issues::numeric / m.total_issues * 50) + (
                                case
                                    when m.avg_issue_age_days < 30
                                    then 25
                                    when m.avg_issue_age_days < 60
                                    then 15
                                    when m.avg_issue_age_days < 90
                                    then 10
                                    else 5
                                end
                            )
                            + (case when m.in_progress_issues > 0 then 25 else 0 end)
                        ),
                        2
                    )
            end as health_score,

            -- Metadata
            current_timestamp as _etl_date
        from project_metrics m
        left join projects p on m.project_key = p.project_key
    )

select *
from final
order by health_score desc nulls last, total_issues desc
