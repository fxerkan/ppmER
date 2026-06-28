{{
    config(
        materialized="incremental",
        schema="core",
        tags=["jira", "core", "dim"],
        incremental_strategy="merge",
        on_schema_change="sync_all_columns",
        unique_key="issue_id",
        indexes=[
            {"columns": ["issue_id"], "unique": True},
            {"columns": ["issue_key"]},
            {"columns": ["parent_key"]},
            {"columns": ["epic_id"]},
            {"columns": ["issue_type"]},
            {"columns": ["project_key"]},
            {"columns": ["status_category"]},
        ],
    )
}}

{#
  Issue Dimension Table

  Comprehensive issue dimension with relationship metrics,
  subtask progress, and time-based calculations.

    Performance optimizations:
  - Epic hierarchy is pre-computed in int_jira__epic_hierarchy (simple join instead of 5-level traversal)
  - Links and subtasks aggregations use indexed staging tables
#}
with
    issues as (
        select *
        from {{ ref("stg_jira__issues") }}
        where
            1 = 1 
            and lower(issue_type) not in ('çalışan')
    )
    ,issue_types as (
        select
            issue_type_id,
            issue_type_name,
            capex_opex,
            issue_type_category,
            is_active,
            item_id
        from {{ ref("stg_shrp__issue_type") }}
    )

    -- Pre-computed epic hierarchy from intermediate model
    ,issue_hierarchy as (
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
    )

    -- Aggregate issue links
    ,links as (
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
    -- worklog_metrics as (
    -- select
    -- issue_key,
    -- count(*) as total_worklogs,
    -- sum(time_spent_seconds) as total_time_spent_seconds,
    -- sum(time_spent_seconds) / 3600.0 as total_hours_logged,
    -- min(work_started_date) as first_worklog_date,
    -- max(work_started_date) as last_worklog_date
    -- from {{ ref('stg_jira__worklogs') }}
    -- group by issue_key
    -- ),
    final as (
        select
            -- Primary key
            i.issue_id,

            -- Issue identifiers
            i.issue_key,
            i.issue_summary,

            -- Issue attributes
            i.issue_type,
            it.issue_type_id,
            it.issue_type_name,
            it.capex_opex,
            it.issue_type_category,
            i.priority,
            i.status_name,
            i.status_category,
            i.resolution,

            -- Project reference
            i.project_id,
            i.project_key,
            i.project_name,

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

            -- Issue Hierarchies - Epic reference
            ih.epic_id,
            ih.epic_key,
            ih.epic_name,
            ih.l1_issue_id,
            ih.l1_issue_key,
            ih.l1_issue_name,
            ih.l2_issue_id,
            ih.l2_issue_key,
            ih.l2_issue_name,

            -- Dates
            i.created_date,
            i.updated_date,
            i.resolution_date,
            i.due_date,

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
            -- coalesce(wm.total_worklogs, 0) as total_worklogs,
            -- coalesce(wm.total_time_spent_seconds, 0) as total_time_spent_seconds,
            -- round(coalesce(wm.total_hours_logged, 0)::numeric, 2) as
            -- total_hours_logged,
            -- wm.first_worklog_date,
            -- wm.last_worklog_date,
            -- Time metrics
            extract(epoch from (current_timestamp - i.created_date)) / 86400 as age_days,
            extract(epoch from (i.updated_date - i.created_date)) / 86400 as time_to_last_update_days,
            case
                when i.resolution_date is not null
                then extract(epoch from (i.resolution_date - i.created_date)) / 86400
                else null
            end as time_to_resolution_days,

            -- Overdue flag
            case
                when
                    i.due_date is not null
                    and i.status_category != 'Done'
                    and i.due_date < current_date
                then true
                else false
            end as is_overdue,

            -- Metadata
            i._dlt_load_id,
            current_timestamp as _etl_date
        from issues i
        left join issue_hierarchy ih on i.issue_id = ih.issue_id
        left join links l on i.issue_key = l.source_issue_key
        left join subtasks s on i.issue_key = s.parent_key
        left join issue_types it on lower(i.issue_type) = lower(it.issue_type_name)
    -- left join worklog_metrics wm on i.issue_key = wm.issue_key
    )

-- Final deduplication to prevent MERGE errors from duplicate issue_ids
-- Joins can sometimes create duplicates, so we ensure one row per issue_id
select distinct on (issue_id) *
from final
order by issue_id, updated_date desc