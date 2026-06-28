{{
    config(
        materialized="view",
        schema="staging",
        tags=["jira", "staging"],
        unique_key="_dlt_id",
    )
}}

with
    source as (select * from {{ source("raw_jira", "issue_links") }}),

    renamed as (
        select
            source_issue_key,
            target_issue_key,
            link_type_name as relationship_type,
            direction as link_direction,
            _dlt_load_id,
            _dlt_id,
            _etl_date
        from source
    )

select *
from renamed
