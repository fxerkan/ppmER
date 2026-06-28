{{
    config(
        materialized="view",
        schema="staging",
        tags=["jira", "staging"],
        unique_key="issue_id",
    )
}}

with
    source as (select * from {{ source("raw_jira", "pbb_issues") }}),

    renamed as (
        select
            s.id as issue_id,
            s.key as issue_key,
            s.summary as issue_summary,
            s.budget_person_days,
            s.project_choice,
            s.budgeting_year,
            s.status_name,
            s.status_category,
            s.assignee_id,
            s.assignee_name,
            s.reporter_id,
            s.reporter_name,
            s.creator_id,
            s.creator_name,
            s.issuetype_name as issue_type,
            s.priority_name as priority,
            s.resolution,
            cast(s.resolutiondate as timestamp) as resolution_date,
            cast(s.created as timestamp) as created_date,
            cast(s.updated as timestamp) as updated_date,
            s._dlt_load_id,
            s._dlt_id,
            _etl_date
        from source s
    )

select *
from renamed
