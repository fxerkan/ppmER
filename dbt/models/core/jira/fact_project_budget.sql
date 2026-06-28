{{
    config(
        materialized="table",
        schema="core",
        tags=["jira", "core", "fact"],
        unique_key="issue_id",
        indexes=[
            {"columns": ["trx_year"]},
            {"columns": ["project_key"]},
        ],
    )
}}

{#
  Project Budget Fact Table

  Budget information from PBB (Proje Butce Bilgileri) issues
  linked to projects for budget tracking and analysis.
#}
with
    pbb_issues as (select * from {{ ref("stg_jira__pbb_issues") }}),

    projects as (
        select
            project_id,
            project_key,
            project_name,
            business_line,
            customer,
            product,
            product_group,
            tribe,
            it_domain
        from {{ ref("stg_jira__projects") }}
    ),

    final as (
        select
            pb.budgeting_year as trx_year,
            -- Calculated fields
            case
                when pb.status_category = 'Done'
                then 'Completed'
                when pb.status_category = 'In Progress'
                then 'Active'
                else 'Pending'
            end as budget_status,

            -- Budget information
            pb.issue_summary as budget_description,
            pb.project_choice,

            pb.budget_person_days,

            -- Linked project context (if project_choice matches a project)
            p.project_id as project_id,
            p.project_key as project_key,
            p.project_name as project_name,
            p.business_line as business_line,
            p.customer as customer,
            p.product as product,
            p.product_group as product_group,
            p.tribe as tribe,
            p.it_domain as it_domain,

            -- Issue identifiers
            pb.issue_id,
            pb.issue_key,
            -- Status
            pb.status_name,
            pb.status_category,
            pb.resolution,
            pb.resolution_date,

            -- User references
            -- pb.assignee_id,
            -- pb.assignee_name,
            pb.reporter_id,
            pb.reporter_name,
            -- pb.creator_id,
            -- pb.creator_name,
            -- Issue metadata
            -- pb.issue_type,
            -- pb.priority,
            -- Dates
            pb.created_date,
            pb.updated_date,

            -- Date dimensions for analysis
            -- date_trunc('month', pb.created_date)::date as created_month,
            -- extract(year from pb.created_date) as created_year,
            -- to_char(pb.created_date, 'YYYY-MM') as created_year_month,
            -- Metadata
            pb._dlt_load_id,
            current_timestamp as _etl_date
        from pbb_issues pb
        left join projects p on pb.project_choice = p.project_name
    )

select *
from final
