{{
    config(
        materialized="table",
        schema="core",
        tags=["jira", "core", "dim"],
        unique_key="user_id",
        indexes=[
            {"columns": ["user_id"], "unique": True},
            {"columns": ["email"]},
            {"columns": ["display_name"]},
        ],
    )
}}

{#
  User Dimension Table

  Combines Jira users with HR data to create a comprehensive
  user dimension with organizational hierarchy, employment details,
  and basic productivity metrics.
#}
with
    users as (select * from {{ ref("stg_jira__users") }}),

    -- Calculate issue statistics per user
    issue_stats as (
        select
            assignee_id as user_id,
            count(*) as total_assigned_issues,
            sum(
                case when status_category = 'Done' then 1 else 0 end
            ) as completed_issues,
            sum(
                case when status_category = 'In Progress' then 1 else 0 end
            ) as in_progress_issues,
            sum(case when status_category = 'To Do' then 1 else 0 end) as todo_issues
        from {{ ref("stg_jira__issues") }}
        where assignee_id is not null
        group by assignee_id
    ),

    reporter_stats as (
        select reporter_id as user_id, count(*) as total_reported_issues
        from {{ ref("stg_jira__issues") }}
        where reporter_id is not null
        group by reporter_id
    ),

    worklog_stats as (
        select
            author_id as user_id,
            count(*) as total_worklogs,
            sum(time_spent_seconds) as total_time_spent_seconds,
            sum(time_spent_seconds) / 3600.0 as total_hours_logged
        from {{ ref("stg_jira__worklogs") }}
        where author_id is not null
        group by author_id
    ),

    final as (
        select
            -- Primary key
            u.user_id,

            -- User identifiers
            u.display_name,
            u.email,
            u.full_name,

            -- Status
            u.is_active,
            u.is_jira_active,
            u.hr_status,
            u.account_type,

            -- Organizational hierarchy (from HR)
            u.unit,
            u.team,
            u.manager_director,
            u.manager_deputy_gm,
            u.deputy_gm_upper_unit,
            u.manages_team,

            -- Employment details (from HR)
            u.outsource_inhouse,
            u.company_info,
            u.employment_start_date,
            u.has_hr_data,

            -- Issue assignment metrics
            coalesce(i.total_assigned_issues, 0) as total_assigned_issues,
            coalesce(i.completed_issues, 0) as completed_issues,
            coalesce(i.in_progress_issues, 0) as in_progress_issues,
            coalesce(i.todo_issues, 0) as todo_issues,
            case
                when coalesce(i.total_assigned_issues, 0) > 0
                then
                    round(
                        i.completed_issues::numeric
                        / i.total_assigned_issues::numeric
                        * 100,
                        2
                    )
                else null
            end as completion_rate_pct,

            -- Reporter metrics
            coalesce(r.total_reported_issues, 0) as total_reported_issues,

            -- Worklog metrics
            coalesce(w.total_worklogs, 0) as total_worklogs,
            coalesce(w.total_time_spent_seconds, 0) as total_time_spent_seconds,
            round(coalesce(w.total_hours_logged, 0)::numeric, 2) as total_hours_logged,

            -- Metadata
            u._dlt_load_id,
            current_timestamp as dbt_updated_date,
            current_timestamp as _etl_date
        from users u
        left join issue_stats i on u.user_id = i.user_id
        left join reporter_stats r on u.user_id = r.user_id
        left join worklog_stats w on u.user_id = w.user_id
    )

select *
from final
