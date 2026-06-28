{{
    config(
        materialized="incremental",
        schema="core",
        tags=["jira", "core", "fact", "incremental"],
        unique_key="issue_id",
        incremental_strategy="merge",
        on_schema_change="append_new_columns",
        indexes=[
            {"columns": ["issue_id"], "unique": True},
            {"columns": ["issue_key"]},
            {"columns": ["period"]},
            {"columns": ["trx_date"]},
        ],
        enabled=false,
    )
}}

{#
  Issue Fact Table (Incremental)

  Stores issues as facts with denormalized context for efficient querying.
  Uses incremental strategy to efficiently process new/updated issues.
#}
with
    issues as (
        -- Deduplicate by issue_id to prevent "MERGE command cannot affect row a second time" error
        -- In incremental mode, we need distinct issue_ids to avoid duplicate merge targets
        select distinct on (issue_id) *
        from {{ ref("stg_jira__issues") }}
        {% if is_incremental() %}
            where updated_date > (select max(updated_date) from {{ this }})
        {% endif %}
        order by issue_id, updated_date desc
    ),
    issues_hierarchy as (
        select
            issue_id,
            issue_key,
            epic_id,
            epic_key,
            epic_name,
            l1_issue_id,
            l1_issue_key,
            l1_issue_name,
            l2_issue_id,
            l2_issue_key,
            l2_issue_name
        from {{ ref("stg_jira__issues_hierarchy") }}
    ),
    projects as (
        select
            project_id,
            project_key,
            project_name,
            business_line,
            customer,
            product,
            product_group,
            tribe,
            it_domain
        from {{ ref("dim_projects") }}
    ),
    -- Aggregate issue links
    links as (
        select
            source_issue_key,
            count(*) as total_links,
            sum(
                case when relationship_type = 'Blocks' then 1 else 0 end
            ) as blocks_count,
            sum(
                case when relationship_type = 'Duplicate' then 1 else 0 end
            ) as duplicates_count,
            sum(
                case when relationship_type = 'Relates' then 1 else 0 end
            ) as relates_count
        from {{ ref("stg_jira__issue_links") }}
        group by source_issue_key
    ),
    -- Aggregate subtasks
    subtasks as (
        select
            parent_key,
            count(*) as total_subtasks,
            sum(
                case when subtask_status = 'Done' then 1 else 0 end
            ) as completed_subtasks,
            sum(case when subtask_status != 'Done' then 1 else 0 end) as open_subtasks
        from {{ ref("stg_jira__issue_subtasks") }}
        group by parent_key
    ),
    -- Aggregate worklogs per issue
    worklog_metrics as (
        select
            issue_id,
            issue_key,
            count(*) as total_worklogs,
            sum(time_spent_seconds) as total_time_spent_seconds,
            sum(time_spent_seconds) / 3600.0 as total_hours_logged
        from {{ ref("stg_jira__worklogs") }}
        group by issue_id, 
                issue_key
    ),
    final as (
        select
            to_char(i.created_date, 'YYYY-MM') as period,
            cast(i.created_date as date) as trx_date,
            -- Primary key
            i.issue_id,
            i.issue_key,

            -- Issue attributes
            i.issue_summary,
            i.issue_type,
            i.priority,
            i.status_name,
            i.status_category,
            i.resolution,

            -- Project context (denormalized)
            i.project_id,
            i.project_key,
            i.project_name,
            p.business_line,
            p.customer,
            p.product,
            p.product_group,
            p.tribe,
            p.it_domain,

            -- User references
            i.assignee_id,
            i.assignee_name,
            i.reporter_id,
            i.reporter_name,
            i.creator_id,
            i.creator_name,

            -- Hierarchy
            i.parent_id,
            i.parent_key,
            i.is_subtask,
            ih.epic_id,
            ih.epic_key,
            ih.epic_name,

            -- Dates
            i.created_date,
            i.updated_date,
            i.resolution_date,
            i.due_date,

            -- Date dimensions for analysis
            -- date_trunc('day', i.created_date)::date as created_day,
            -- date_trunc('week', i.created_date)::date as created_week,
            -- date_trunc('month', i.created_date)::date as created_month,
            -- extract(year from i.created_date) as created_year,
            -- Relationship metrics
            coalesce(l.total_links, 0) as total_issue_links,
            coalesce(l.blocks_count, 0) as blocks_count,
            coalesce(l.duplicates_count, 0) as duplicates_count,
            coalesce(l.relates_count, 0) as relates_count,

            -- Subtask metrics
            coalesce(s.total_subtasks, 0) as total_subtasks,
            coalesce(s.completed_subtasks, 0) as completed_subtasks,
            coalesce(s.open_subtasks, 0) as open_subtasks,
            case
                when s.total_subtasks > 0
                then
                    round(
                        s.completed_subtasks::numeric / s.total_subtasks::numeric * 100,
                        2
                    )
                else null
            end as subtask_completion_pct,

            -- Worklog metrics
            coalesce(wm.total_worklogs, 0) as total_worklogs,
            coalesce(wm.total_time_spent_seconds, 0) as total_time_spent_seconds,
            round(coalesce(wm.total_hours_logged, 0)::numeric, 2) as total_hours_logged,

            -- Time metrics
            round(
                extract(epoch from (current_timestamp - i.created_date)) / 86400, 2
            ) as age_days,
            round(
                extract(epoch from (i.updated_date - i.created_date)) / 86400, 2
            ) as time_to_last_update_days,
            case
                when i.resolution_date is not null
                then
                    round(
                        extract(epoch from (i.resolution_date - i.created_date))
                        / 86400,
                        2
                    )
                else null
            end as time_to_resolution_days,

            -- Status flags
            case
                when
                    i.due_date is not null
                    and i.status_category != 'Done'
                    and i.due_date < current_date
                then true
                else false
            end as is_overdue,

            case when i.status_category = 'Done' then true else false end as is_done,
            case
                when i.status_category = 'In Progress' then true else false
            end as is_in_progress,
            case when i.status_category = 'To Do' then true else false end as is_todo,

            -- Metadata
            i._dlt_load_id,
            current_timestamp as _etl_date
        from issues i
        left join projects p on i.project_id = p.project_id
        left join links l on i.issue_key = l.source_issue_key
        left join subtasks s on i.issue_key = s.parent_key
        left join worklog_metrics wm on i.issue_id = wm.issue_id
        left join issues_hierarchy ih on i.issue_id = ih.issue_id
    )

-- Final deduplication to prevent MERGE errors from duplicate issue_ids
-- Joins can sometimes create duplicates, so we ensure one row per issue_id
select distinct on (issue_id) *
from final
order by issue_id, updated_date desc
