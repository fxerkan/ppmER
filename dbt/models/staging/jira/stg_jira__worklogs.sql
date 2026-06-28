{{
    config(
        materialized="view",
        schema="staging",
        tags=["jira", "staging"],
        unique_key="worklog_id",
    )
}}

with
    source as (select * from {{ source("raw_jira", "worklogs") }}),

    -- Deduplicate by keeping the most recent version of each worklog
    deduplicated as (
        select
            *, row_number() over (partition by id order by _dlt_load_id desc) as row_num
        from source
    ),

    renamed as (
        select
            id as worklog_id,
            issue_key,
            issue_id,
            author_id,
            author_name,
            cast(started as timestamp)  as work_started_date,
            time_spent as time_spent_display,
            time_spent_seconds,
            cast(created as timestamp)  as created_date,
            cast(updated as timestamp)  as updated_date,
            _dlt_load_id,
            _dlt_id,
            _etl_date
        from deduplicated
        where row_num = 1
    )

select *
from renamed
