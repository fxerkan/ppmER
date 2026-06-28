{{
    config(
        materialized="view",
        schema="staging",
        tags=["jira", "staging"],
        unique_key="issue_id",
    )
}}

{#
  Jira Issues Staging Model with Safe JSON Parsing

  This model handles description field parsing with multiple fallback strategies:
  1. NULL/empty values → NULL
  2. Valid JSON → Parse using Jira's ADF format
  3. Invalid JSON → Return NULL (safe fallback)
  4. Plain text → Return as-is
#}

with
    source as (
        select *
        from {{ source("raw_jira", "issues") }}
        where 1 = 1 and lower(issuetype_name) not in ('çalışan')
    ),
    -- Deduplicate by keeping the most recent version of each issue
    deduplicated as (
        select
            *, row_number() over (partition by id order by _dlt_load_id desc) as row_num
        from source
    ),
    -- Safe JSON parsing using custom PostgreSQL function with exception handling
    -- The safe_json_text_extract function handles all errors gracefully
    safe_description as (
        select
            d.*,
            -- Multi-level safe parsing for description field
            case
                -- Level 1: NULL or empty - return NULL
                when d.description is null
                    or trim(d.description) = ''
                    or d.description = '""'
                    or d.description = 'null'
                    or length(trim(d.description)) < 2 then
                    null

                -- Level 2: Try to parse as Jira ADF JSON format using safe function
                -- The safe_json_text_extract function will return NULL on any parsing error
                else
                    nullif(trim(
                        coalesce(safe_json_text_extract(d.description, '$.content[0].content[0].text'), '')
                        || ' ' ||
                        coalesce(safe_json_text_extract(d.description, '$.content[0].content[1].text'), '')
                        || ' ' ||
                        coalesce(safe_json_text_extract(d.description, '$.content[1].content[0].text'), '')
                        || ' ' ||
                        coalesce(safe_json_text_extract(d.description, '$.content[1].content[1].text'), '')
                        || ' ' ||
                        coalesce(safe_json_text_extract(d.description, '$.content[2].content[0].text'), '')
                    ), '')
            end as description_parsed
        from deduplicated d
        where d.row_num = 1
    ),
    renamed as (
        select
            sd.id as issue_id,
            sd.key as issue_key,
            sd.summary as issue_summary,
            sd.status_name,
            sd.status_category,
            sd.issuetype_name as issue_type,
            sd.priority_name as priority,
            sd.project_id,
            sd.project_key,
            sd.project_name,
            sd.parent_id,
            sd.parent_key,
            sd.is_subtask,
            sd.assignee_id,
            sd.assignee_name,
            sd.reporter_id,
            sd.reporter_name,
            sd.creator_id,
            sd.creator_name,
            -- Use safe parsed description
            sd.description_parsed as description,
            -- Parse labels with safe handling
            nullif(trim(translate(sd.labels, '[]"', '')), '') as labels,
            cast(sd.created as timestamp)  as created_date,
            cast(sd.updated as timestamp) as updated_date,
            sd.resolution,
            cast(sd.resolutiondate as timestamp)  as resolution_date,
            cast(sd.duedate as date) as due_date,
            sd._dlt_load_id,
            sd._dlt_id,
            sd._etl_date
        from safe_description sd
    )

select *
from renamed
