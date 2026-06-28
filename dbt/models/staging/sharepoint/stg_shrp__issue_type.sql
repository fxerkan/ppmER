{{
    config(
        materialized="view",
        schema="staging",
        tags=["sharepoint", "staging"],
        unique_key="sharepoint_item_id",
    )
}}

{#
  SharePoint Issue Type Staging Model

  Master data for Jira issue type classifications.
  Maps issue types to expense categories (Expensed vs Capitalized) for financial reporting.
#}

with
    source as (select * from {{ source("raw_sharepoint", "issue_type") }}),

    renamed as (
        select
            cast(field_2 as integer) as issue_type_id,
            title as issue_type_name,
            field_1 as capex_opex,
            category as issue_type_category,
            case
                when lower(active) in ('evet','yes') then true
                when lower(active) in ('hayir','hayır','no') then false
                else false
            end as is_active,
            cast(id as varchar) as item_id,
            cast(created as timestamp) as created_date,
            cast(modified as timestamp) as modified_date,
            _dlt_load_id,
            _dlt_id,
            _etl_date
        from source
    )

select *
from renamed
