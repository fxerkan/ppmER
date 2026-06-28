{{
    config(
        materialized="table",
        schema="core",
        tags=["jira", "core", "dim"],
        unique_key="project_id",
        indexes=[
            {"columns": ["project_id"], "unique": True},
            {"columns": ["project_key"]},
        ],
    )
}}

{#
  Project Dimension Table

  Combines Jira projects with portfolio properties and aggregated metrics
  to create a comprehensive project dimension for analytics.
#}
with
    projects as (select * from {{ ref("stg_jira__projects") }}),

    -- Calculate issue metrics per project
    issue_metrics as (
        select
            project_key,
            count(distinct issue_id) as total_issues,
            count(
                distinct case when status_category = 'Done' then issue_id end
            ) as completed_issues,
            count(
                distinct case when status_category = 'In Progress' then issue_id end
            ) as in_progress_issues,
            count(
                distinct case when status_category = 'To Do' then issue_id end
            ) as todo_issues,
            count(distinct assignee_id) as unique_assignees,
            count(distinct reporter_id) as unique_reporters,
            min(created_date) as first_issue_created_date,
            max(updated_date) as last_issue_updated_date
        from {{ ref("stg_jira__issues") }}
        group by project_key
    ),

    -- Calculate worklog metrics per project
    worklog_metrics as (
        select
            i.project_key,
            count(distinct w.worklog_id) as total_worklogs,
            sum(w.time_spent_seconds) / 3600.0 as total_hours_logged
        from {{ ref("stg_jira__worklogs") }} w
        join {{ ref("stg_jira__issues") }} i on w.issue_key = i.issue_key
        group by i.project_key
    ),

    final as (
        select
            -- Primary key
            p.project_id,

            -- Project identifiers
            p.project_key,
            p.project_name,
            p.project_description,
            p.project_type,
            p.category_id,
            p.category_name,
            p.is_private,

            -- Portfolio properties
            p.business_line,
            p.customer,
            p.hosting,
            p.portfolio_id,
            p.it_domain,
            p.product,
            p.product_group,
            p.tribe,
            p.open_closed,

            -- Distribution effort fields
            p.app_mgmt_distribution_effort,
            p.itops_distribution_effort,
            p.infosec_distribution_effort,
            p.l1_distribution_effort,
            p.l2_distribution_effort,

            -- Subject to distribution flags
            p.subject_to_l1_distribution,
            p.subject_to_app_mgmt_distribution,
            p.subject_to_itops_distribution,

            -- Financial reporting
            p.financial_code,
            p.financial_report_display,

            -- DevOps properties
            p.devops_deployment_apps,

            -- Issue metrics
            coalesce(im.total_issues, 0) as total_issues,
            coalesce(im.completed_issues, 0) as completed_issues,
            coalesce(im.in_progress_issues, 0) as in_progress_issues,
            coalesce(im.todo_issues, 0) as todo_issues,
            coalesce(im.unique_assignees, 0) as unique_assignees,
            coalesce(im.unique_reporters, 0) as unique_reporters,
            im.first_issue_created_date,
            im.last_issue_updated_date,

            -- Completion percentage
            case
                when coalesce(im.total_issues, 0) > 0
                then round(100.0 * im.completed_issues / im.total_issues, 2)
                else 0
            end as completion_pct,

            -- Worklog metrics
            coalesce(wm.total_worklogs, 0) as total_worklogs,
            round(coalesce(wm.total_hours_logged, 0)::numeric, 2) as total_hours_logged,

            -- Metadata
            p._dlt_load_id,
            current_timestamp as dbt_updated_date,
            current_timestamp as _etl_date
        from projects p
        left join issue_metrics im on p.project_key = im.project_key
        left join worklog_metrics wm on p.project_key = wm.project_key
    )

select *
from final
