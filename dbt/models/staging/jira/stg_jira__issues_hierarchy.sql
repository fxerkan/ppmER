{{
    config(
        materialized="incremental",
        schema="staging",
        tags=["jira", "staging"],
        incremental_strategy="merge",
        unique_key="issue_id",
        on_schema_change="sync_all_columns",
        post_hook=[
            "CREATE INDEX IF NOT EXISTS idx_stg__issues_epic_hierarchy_issue_id ON {{ this }} (issue_id)",
            "CREATE INDEX IF NOT EXISTS idx_stg__issues_epic_hierarchy_issue_key ON {{ this }} (issue_key)",
            "CREATE INDEX IF NOT EXISTS idx_stg__issues_epic_hierarchy_epic_id ON {{ this }} (epic_id) WHERE epic_id IS NOT NULL",
        ],
    )
}}

{#
  Pre-computed Epic Hierarchy Resolution + Denormalized Issue Hierarchy

  This intermediate model resolves the epic for each issue by traversing
  the parent hierarchy up to 5 levels. Materialized as incremental table
  to avoid repeated computation in downstream models.

  Outputs:
  - epic_id, epic_key, epic_name: The epic found in the hierarchy
  - l1_* through l5_*: Denormalized parent hierarchy (l1 = direct parent, l5 = great-great-great grandparent)

  Performance optimization:
  - Uses lightweight lookup from raw table (no JSON parsing)
  - 5-level iterative LEFT JOIN instead of recursive CTE
  - Incremental processing for new/updated issues
#}
with
    issue_base as (
        select
            issue_id,
            issue_key,
            issue_summary,
            issue_type,
            parent_id,
            parent_key,
            lower(issue_type) in ('epik', 'epic') as is_epic,
            _dlt_load_id,
            _etl_date
        from {{ ref("stg_jira__issues") }}
        where
            1 = 1 and lower(issue_type) not in ('çalışan')
            {% if is_incremental() %}
                and _dlt_load_id
                > (select coalesce(max(_dlt_load_id), '') from {{ this }})
            {% endif %}
    ),

    -- Lightweight lookup for parent resolution (full table for hierarchy traversal)
    issue_lookup as (
        select
            issue_key,
            issue_id,
            issue_summary,
            issue_type,
            parent_id,
            parent_key,
            is_epic
        from issue_base
    ),

    -- Resolve epic hierarchy using iterative LEFT joins (max 5 levels)
    epic_resolved as (
        select
            i.issue_id,
            i.issue_key,
            i.issue_summary,
            i.issue_type,
            i.parent_id,
            i.parent_key,
            -- Epic resolution (unchanged logic)
            coalesce(
                case when i.is_epic then i.issue_id end,
                case when p1.is_epic then p1.issue_id end,
                case when p2.is_epic then p2.issue_id end,
                case when p3.is_epic then p3.issue_id end,
                case when p4.is_epic then p4.issue_id end,
                case when p5.is_epic then p5.issue_id end
            ) as epic_id,
            coalesce(
                case when i.is_epic then i.issue_key end,
                case when p1.is_epic then p1.issue_key end,
                case when p2.is_epic then p2.issue_key end,
                case when p3.is_epic then p3.issue_key end,
                case when p4.is_epic then p4.issue_key end,
                case when p5.is_epic then p5.issue_key end
            ) as epic_key,
            coalesce(
                case when i.is_epic then i.issue_summary end,
                case when p1.is_epic then p1.issue_summary end,
                case when p2.is_epic then p2.issue_summary end,
                case when p3.is_epic then p3.issue_summary end,
                case when p4.is_epic then p4.issue_summary end,
                case when p5.is_epic then p5.issue_summary end
            ) as epic_name,
            -- Denormalized hierarchy: Level 1 (direct parent)
            p1.issue_id as l1_issue_id,
            p1.issue_key as l1_issue_key,
            p1.issue_summary as l1_issue_name,
            p1.issue_type as l1_issue_type,
            -- Denormalized hierarchy: Level 2 (grandparent)
            p2.issue_id as l2_issue_id,
            p2.issue_key as l2_issue_key,
            p2.issue_summary as l2_issue_name,
            p2.issue_type as l2_issue_type,
            -- Denormalized hierarchy: Level 3 (great-grandparent)
            p3.issue_id as l3_issue_id,
            p3.issue_key as l3_issue_key,
            p3.issue_summary as l3_issue_name,
            p3.issue_type as l3_issue_type,
            -- Denormalized hierarchy: Level 4 (great-great-grandparent)
            p4.issue_id as l4_issue_id,
            p4.issue_key as l4_issue_key,
            p4.issue_summary as l4_issue_name,
            p4.issue_type as l4_issue_type,
            -- Denormalized hierarchy: Level 5 (great-great-great-grandparent)
            p5.issue_id as l5_issue_id,
            p5.issue_key as l5_issue_key,
            p5.issue_summary as l5_issue_name,
            p5.issue_type as l5_issue_type,
            i._dlt_load_id,
            i._etl_date
        from issue_base i
        left join issue_lookup p1 on i.parent_key = p1.issue_key
        left join issue_lookup p2 on p1.parent_key = p2.issue_key
        left join issue_lookup p3 on p2.parent_key = p3.issue_key
        left join issue_lookup p4 on p3.parent_key = p4.issue_key
        left join issue_lookup p5 on p4.parent_key = p5.issue_key
    )

select *
from epic_resolved
