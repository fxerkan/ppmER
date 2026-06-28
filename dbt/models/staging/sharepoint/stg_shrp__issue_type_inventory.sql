{{
    config(
        materialized="view",
        schema="staging",
        tags=["sharepoint", "staging"],
        unique_key="sharepoint_item_id",
    )
}}

{#
  SharePoint Issue Type Inventory Staging Model

  Task type definitions with detailed descriptions.
  Used for categorizing and describing different types of work.
#}

with
    source as (select * from {{ source("raw_sharepoint", "issue_type_inventory") }}),

    renamed as (
        select
            cast(id as varchar) as item_id,
            title as issue_type_name,
            description as issue_type_description,
            task_type as issue_type_category,
            --task_type_description,
            expensed_x002f_capitalized as expense_classification,
            cast(created as timestamp) as create_date,
            cast(modified as timestamp) as update_date,
            _dlt_load_id,
            _dlt_id,
            _etl_date
        from source
    )

select *
from renamed
