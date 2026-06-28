{{
    config(
        materialized="table",
        schema="core",
        tags=["jira", "core", "map", "bridge"],
        unique_key="_dlt_id",
    )
}}

{#
  Issue Links Bridge Table

  Many-to-many relationship table between issues.
  Stores relationships like: Blocks, Duplicates, Relates To, etc.
#}
with
    issue_links as (select * from {{ ref("stg_jira__issue_links") }}),

    source_issues as (
        select
            issue_id,
            issue_key,
            issue_summary,
            issue_type,
            status_name,
            status_category,
            project_key
        from {{ ref("stg_jira__issues") }}
    ),

    target_issues as (
        select
            issue_id,
            issue_key,
            issue_summary,
            issue_type,
            status_name,
            status_category,
            project_key
        from {{ ref("stg_jira__issues") }}
    ),

    final as (
        select
            -- Primary key (composite)
            il._dlt_id as link_id,

            -- Source issue
            il.source_issue_key,
            si.issue_id as source_issue_id,
            si.issue_summary as source_issue_summary,
            si.issue_type as source_issue_type,
            si.status_name as source_status_name,
            si.status_category as source_status_category,
            si.project_key as source_project_key,

            -- Target issue
            il.target_issue_key,
            ti.issue_id as target_issue_id,
            ti.issue_summary as target_issue_summary,
            ti.issue_type as target_issue_type,
            ti.status_name as target_status_name,
            ti.status_category as target_status_category,
            ti.project_key as target_project_key,

            -- Link attributes
            il.relationship_type,
            il.link_direction,

            -- Cross-project flag
            case
                when si.project_key != ti.project_key then true else false
            end as is_cross_project_link,

            -- Blocking analysis
            case
                when il.relationship_type = 'Blocks' and ti.status_category != 'Done'
                then true
                else false
            end as is_active_blocker,

            -- Metadata
            il._dlt_load_id,
            current_timestamp as dbt_updated_date,
            current_timestamp as _etl_date
        from issue_links il
        left join source_issues si on il.source_issue_key = si.issue_key
        left join target_issues ti on il.target_issue_key = ti.issue_key
    )

select *
from final
