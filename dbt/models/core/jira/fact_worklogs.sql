{{
    config(
        materialized="incremental",
        schema="core",
        tags=["jira", "core", "fact", "incremental"],
        unique_key="worklog_id",
        incremental_strategy="merge",
        on_schema_change="append_new_columns",
        indexes=[
            {"columns": ["worklog_id"], "unique": True},
            {"columns": ["period"]},
            {"columns": ["trx_date"]},
            {"columns": ["issue_id"]},
            {"columns": ["author_id"]},
            {"columns": ["author_name"]},
        ],
        post_hook="DELETE FROM {{ this }} fw WHERE NOT EXISTS (SELECT 1 FROM {{ ref('stg_jira__worklogs') }} s WHERE s.worklog_id = fw.worklog_id)"
    )
}}

{#
  Worklog Fact Table (Incremental)

  Stores time tracking entries with denormalized issue and user context.
  Uses incremental strategy to efficiently process new/updated worklogs.
#}
with
    worklogs as (
        select *
        from {{ ref("stg_jira__worklogs") }}
    ),
--fact worklog tablosundaki max update date alıyor daha sonra stg jira_worklogsa kriter olarak verip bu tarihten sonra olan kayıtları getirip üstüne güncelliyor.
    issues as (
        select
            issue_id,
            issue_key,
            issue_summary,
            issue_type,
            issue_type_id,
            issue_type_name,
            capex_opex,
            issue_type_category,
            priority,
            status_name,
            status_category,
            project_id,
            project_key,
            project_name,
            epic_id,
            epic_key,
            epic_name
        from {{ ref("dim_issues") }}
    ),

    users as (
        select user_id, display_name, full_name, email, unit, team
        from {{ ref("dim_users") }}
    ),

    hr_user as (
        select  is_outsource_inhouse, user_name, deputy_gm_upper_unit, deputy_gm_name, unit_name, exit_date
        from {{ ref("dim_hr") }}
    ),

    projects as (
        select
            project_id,
            project_key,
            category_name,
            is_private,
            business_line,
            customer,
            hosting,
            portfolio_id,
            it_domain,
            product,
            product_group,
            tribe,
            open_closed,
            app_mgmt_distribution_effort,
            itops_distribution_effort,
            infosec_distribution_effort,
            l1_distribution_effort,
            l2_distribution_effort,
            financial_code
        from {{ ref("dim_projects") }}
    ),

    final as (
        select
            -- Transaction date for partitioning
            to_char(w.work_started_date, 'YYYY-MM') as period,
            date_trunc('day', w.work_started_date)::date as trx_date,

            -- Primary key
            w.worklog_id,

            -- Issue context
            w.issue_id,
            coalesce(w.issue_key, i.issue_key) as issue_key,
            -- i.issue_summary,
            i.issue_type,
            i.issue_type_id,
            i.issue_type_name,
            i.capex_opex,
            i.issue_type_category,
            -- i.priority,
            -- i.status_name,
            -- i.status_category,

            --Project info
            i.project_id,
            i.project_key,
            i.project_name,

            -- Author context
            w.author_id,
            w.author_name,
            u.full_name as author_full_name,
            u.email as author_email,
            u.unit as author_unit,
            u.team as author_team,

            --HR
            hr.is_outsource_inhouse,
            hr.deputy_gm_upper_unit,
            hr.unit_name,
            hr.exit_date,

            -- Time tracking
            w.time_spent_display,
            w.time_spent_seconds,
            round(w.time_spent_seconds / 3600.0, 2) as time_spent_hours,
            (w.time_spent_seconds/3600.0)/8 as time_spent_person_days,  -- 8 hours = 1 person day

            
            -- Project context
            i.epic_id,
            i.epic_key,
            i.epic_name,
            p.category_name,
            p.is_private,
            -- Portfolio properties
            p.business_line,
            p.customer,
            p.hosting,
            p.portfolio_id,
            p.it_domain,
            p.product,
            p.product_group,
            p.tribe,
            p.open_closed,
            -- Distribution effort fields
            p.app_mgmt_distribution_effort,
            p.itops_distribution_effort,
            p.infosec_distribution_effort,
            p.l1_distribution_effort,
            p.l2_distribution_effort,
             -- Financial reporting
            p.financial_code,

            -- Timestamps
            w.work_started_date,
            w.created_date,
            w.updated_date,

            -- Metadata
            w._dlt_load_id,
            current_timestamp as _etl_date
        from worklogs w
        --left join issues i on w.issue_key = i.issue_key -- data quality issues with issue_key = NULL
        left join issues i on w.issue_id = i.issue_id
        left join users u on w.author_id = u.user_id
        left join projects p on i.project_id = p.project_id
        left join hr_user hr on w.author_name = hr.user_name
    )
select *
from final
where 1=1
and trx_date <= current_date
