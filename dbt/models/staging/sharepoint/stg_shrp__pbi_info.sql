{{
    config(
        materialized="view",
        schema="staging",
        tags=["sharepoint", "staging"],
        unique_key="sharepoint_item_id",
    )
}}

{#
  SharePoint PBI Info Staging Model

  Power BI project/team mapping information.
  Maps Jira project IDs to team names for Power BI reporting.
#}

with
    source as (select * from {{ source("raw_sharepoint", "pbi_info") }}),

    renamed as (
        select
            cast(id as varchar) as item_id,
            title as jira_project_id,
            field_1 as team_name,
            cast(created as timestamp) as created_date,
            cast(modified as timestamp) as modified_date,
            _dlt_load_id,
            _dlt_id,
            _etl_date
        from source
    )

select *
from renamed
