{{
    config(
        materialized="view",
        schema="staging",
        tags=["jira", "staging"],
        unique_key="_dlt_id",
    )
}}

with
    source as (select * from {{ source("raw_jira", "issue_subtasks") }}),

    renamed as (
        select
            parent_key,
            subtask_key,
            subtask_summary,
            subtask_status,
            _dlt_load_id,
            _dlt_id,
            _etl_date
        from source
    )

select *
from renamed
