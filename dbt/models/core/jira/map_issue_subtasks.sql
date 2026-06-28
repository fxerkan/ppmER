{{
    config(
        materialized="table",
        schema="core",
        tags=["jira", "core", "map", "bridge"],
        unique_key="_dlt_id",
    )
}}

{#
  Issue Subtasks Bridge Table

  Parent-child relationship table for subtasks.
  Connects parent issues with their subtasks.
#}
with
    issue_subtasks as (select * from {{ ref("stg_jira__issue_subtasks") }}),

    parent_issues as (
        select
            issue_id,
            issue_key,
            issue_summary,
            issue_type,
            status_name,
            status_category,
            project_key,
            assignee_id,
            assignee_name
        from {{ ref("stg_jira__issues") }}
    ),

    subtask_issues as (
        select
            issue_id,
            issue_key,
            issue_summary,
            issue_type,
            status_name,
            status_category,
            project_key,
            assignee_id,
            assignee_name,
            created_date,
            updated_date,
            resolution_date
        from {{ ref("stg_jira__issues") }}
    ),

    final as (
        select
            -- Primary key
            ist._dlt_id as subtask_link_id,

            -- Parent issue
            ist.parent_key,
            pi.issue_id as parent_issue_id,
            pi.issue_summary as parent_issue_summary,
            pi.issue_type as parent_issue_type,
            pi.status_name as parent_status_name,
            pi.status_category as parent_status_category,
            pi.project_key,
            pi.assignee_id as parent_assignee_id,
            pi.assignee_name as parent_assignee_name,

            -- Subtask
            ist.subtask_key,
            si.issue_id as subtask_issue_id,
            ist.subtask_summary,
            ist.subtask_status,
            si.issue_type as subtask_issue_type,
            si.status_category as subtask_status_category,
            si.assignee_id as subtask_assignee_id,
            si.assignee_name as subtask_assignee_name,
            si.created_date as subtask_created_date,
            si.updated_date as subtask_updated_date,
            si.resolution_date as subtask_resolution_date,

            -- Status flags
            case
                when ist.subtask_status = 'Done' then true else false
            end as is_subtask_done,
            case
                when si.status_category = 'In Progress' then true else false
            end as is_subtask_in_progress,

            -- Time metrics
            case
                when si.resolution_date is not null and si.created_date is not null
                then
                    round(
                        extract(epoch from (si.resolution_date - si.created_date))
                        / 86400,
                        2
                    )
                else null
            end as subtask_resolution_days,

            -- Metadata
            ist._dlt_load_id,
            current_timestamp as dbt_updated_date,
            current_timestamp as _etl_date
        from issue_subtasks ist
        left join parent_issues pi on ist.parent_key = pi.issue_key
        left join subtask_issues si on ist.subtask_key = si.issue_key
    )

select *
from final
