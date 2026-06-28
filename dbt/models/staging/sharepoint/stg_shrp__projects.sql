{{
    config(
        materialized="view",
        schema="staging",
        tags=["sharepoint", "staging"],
        unique_key="sharepoint_item_id",
    )
}}

{#
  SharePoint Projects Staging Model

  Master project registry that maps Jira project IDs to SharePoint project metadata.
  This table provides the bridge between Jira projects and SharePoint project tracking.
#}

with
    source as (select * from {{ source("raw_sharepoint", "projects") }}),

    renamed as (
        select
            cast(id as varchar) as item_id,
            title as project_title,
            cast(field_0 as varchar) as jira_project_id,
            id_project,
            field_3 as category,
            field_2 as customer,
            field_4 as it_domain,
            field_5 as tribe,
            field_6 as product_group,
            field_7 as product,
            field_8 as hosting_type,
            field_9 as business_line,
            cast(created as timestamp) as created_date,
            cast(modified as timestamp) as modified_date,
            _dlt_load_id,
            _dlt_id,
            _etl_date
        from source
    )

select *
from renamed
