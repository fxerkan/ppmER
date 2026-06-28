{{
    config(
        materialized="view",
        schema="staging",
        tags=["sharepoint", "staging"],
        unique_key="sharepoint_item_id",
    )
}}

{#
  SharePoint Project Risks Staging Model

  Risk tracking entries linked to projects in the Project Inventory list.
#}

with
    source as (select * from {{ source("raw_sharepoint", "proje_risks") }}),

    renamed as (
        select
            cast(id as varchar) as item_id,
            title as project_code,
            risk as risk_description,
            risk_durumu as risk_status,
            project_information_lookup_id as proje_inv_id,
            project_names_lookup_id as project_names_id,
            field_13 as project_id,
            cast(modified as timestamp) as modified_at,
            cast(created as timestamp) as created_at,
            _dlt_load_id,
            _dlt_id,
            _etl_date
        from source
    )

select *
from renamed
