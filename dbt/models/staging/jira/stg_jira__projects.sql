{{
    config(
        materialized="view",
        schema="staging",
        tags=["jira", "staging"],
        unique_key="project_id",
    )
}}

{#
  Projects Staging Model with Denormalized Properties

  Joins project data with pivoted project properties to create
  a wide table with all portfolio attributes as columns.
#}
with
    source as (select * from {{ source("raw_jira", "projects") }}),

    renamed as (
        select
            cast(id as varchar) as project_id,
            key as project_key,
            name as project_name,
            description as project_description,
            project_type_key as project_type,
            project_category__id as category_id,
            project_category__name as category_name,
            is_private,
            _dlt_load_id,
            _dlt_id,
            _etl_date
        from source
    ),

    -- Pivot project properties into columns
    properties_pivoted as (
        select
            project_id,
            -- Portfolio properties (from pp-* fields)
            max(
                case when property_name_clean = 'Business Line' then parsed_value end
            ) as business_line,
            max(
                case when property_name_clean = 'Customer' then parsed_value end
            ) as customer,
            max(
                case when property_name_clean = 'Hosting' then parsed_value end
            ) as hosting,
            max(
                case when property_name_clean = 'ID' then parsed_value end
            ) as portfolio_id,
            max(
                case when property_name_clean = 'IT Domain' then parsed_value end
            ) as it_domain,
            max(
                case when property_name_clean = 'Product' then parsed_value end
            ) as product,
            max(
                case when property_name_clean = 'Product Group' then parsed_value end
            ) as product_group,
            max(case when property_name_clean = 'Tribe' then parsed_value end) as tribe,
            max(
                case when property_name_clean = 'Open.Closed' then parsed_value end
            ) as open_closed,
            -- Distribution effort fields
            max(
                case
                    when
                        property_name_clean
                        = 'Application Management Distribution Effort'
                    then parsed_value
                end
            ) as app_mgmt_distribution_effort,
            max(
                case
                    when property_name_clean = 'ITOPS Distribution Effort'
                    then parsed_value
                end
            ) as itops_distribution_effort,
            max(
                case
                    when
                        property_name_clean = 'Information Security Distribution Effort'
                    then parsed_value
                end
            ) as infosec_distribution_effort,
            max(
                case
                    when property_name_clean = 'L1 Distribution Effort'
                    then parsed_value
                end
            ) as l1_distribution_effort,
            max(
                case
                    when property_name_clean = 'L2 Distribution Effort'
                    then parsed_value
                end
            ) as l2_distribution_effort,
            -- Subject to distribution flags
            max(
                case
                    when
                        property_name_clean = 'Subject to L1 Distribution'
                    then parsed_value
                end
            ) as subject_to_l1_distribution,
            max(
                case
                    when
                        property_name_clean = 'Subject to App Management Distribution'
                    then parsed_value
                end
            ) as subject_to_app_mgmt_distribution,
            max(
                case
                    when
                        property_name_clean = 'Subject to ITOPS Distribution'
                    then parsed_value
                end
            ) as subject_to_itops_distribution,
           
            -- Financialcode
            max(
                case
                    when property_name_clean = 'Financial Code'
                    then parsed_value
                end
            ) as financial_code,
             -- Financial reporting
            max(
                case
                    when property_name_clean = 'Financial Report Display'
                    then parsed_value
                end
            ) as financial_report_display,
            -- DevOps properties
            max(
                case
                    when property_name_clean = 'DevOps.ProjectSelectedDeploymentApps'
                    then parsed_value
                end
            ) as devops_deployment_apps
        from {{ ref("stg_jira__project_properties") }}
        group by project_id
    )

select
    p.project_id,
    p.project_key,
    p.project_name,
    p.project_description,
    p.project_type,
    p.category_id,
    p.category_name,
    p.is_private,
    -- Portfolio properties
    pp.business_line,
    pp.customer,
    pp.hosting,
    pp.portfolio_id,
    pp.it_domain,
    pp.product,
    pp.product_group,
    pp.tribe,
    pp.open_closed,
    -- Distribution effort fields
    pp.app_mgmt_distribution_effort,
    pp.itops_distribution_effort,
    pp.infosec_distribution_effort,
    pp.l1_distribution_effort,
    pp.l2_distribution_effort,
    -- Subject to distribution flags
    pp.subject_to_l1_distribution,
    pp.subject_to_app_mgmt_distribution,
    pp.subject_to_itops_distribution,
    -- Financial reporting
    pp.financial_code,
    pp.financial_report_display,
    -- DevOps properties
    pp.devops_deployment_apps,
    -- Metadata
    p._dlt_load_id,
    p._dlt_id,
    p._etl_date
from renamed p
left join properties_pivoted pp on p.project_id = pp.project_id
