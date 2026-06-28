{{
    config(
        materialized="view",
        schema="staging",
        tags=["sharepoint", "staging"],
        unique_key="sharepoint_item_id",
    )
}}

{#
  SharePoint Project Inventory Staging Model

  Detailed project tracking with status, timeline, scope, and risk information.
  This is the main project status tracking table used for executive reporting.
#}

with
    source as (select * from {{ source("raw_sharepoint", "proje_inv") }}),

    renamed as (
        select
            cast(id as varchar) as item_id,
            title as project_code,
            field_1 as project_name,
            project_category,
            field_2 as customer,
            field_4 as it_domain,
            field_5 as tribe,
            field_7 as product,
            field_8 as hosting_type,
            field_9 as business_type,
            field_11 as finance_code,
            field_13 as jira_project_id,
            field_12 as project_status,
            on_track_x002f_delayed as on_track_delayed,
            status_progress,
            project_timeline,
            project_scope,
            case
                when executive_dashboard = '1' then true
                when executive_dashboard = '0' then false
                else null
            end as is_executive_dashboard,
            case
                when is_strategic_portfolio_x003fx = '1' then true
                when is_strategic_portfolio_x003fx = '0' then false
                else null
            end as is_strategic_portfolio,
            risk_x002f_problem as risk_problem,
            scope_risk as scope_risk,
            cast(escalation as integer) as escalation,
            customer_light,
            --risk_var_m_x0131__x003fx as has_risk,
            risk_var_m_x0131_x003fx as has_risk,
            project_manager_lookup_id as project_manager_id,
            portfolio_manager_lookup_id as portfolio_manager_id,
            it_tribe_lead_lookup_id as it_tribe_lead_id,

            cast(created as timestamp) as created_date,
            cast(updated as timestamp) as updated_date,
            cast(modified as timestamp) as modified_date,
            _dlt_load_id,
            _dlt_id,
            _etl_date
        from source
    )

select *
from renamed
