{{
    config(
        materialized="view",
        schema="mart",
        tags=["error_check", "master_data", "data_quality"]
    )
}}

/*
  ERROR CHECK: dim_projects - Missing Critical Data

  Description:
  Identifies projects in dim_projects that are missing critical master data fields.
  These missing fields can cause calculation errors or incomplete reporting.

  Expected Result:
  - Empty result = No errors found
  - Rows returned = Projects with missing data that need correction

  Critical Fields Checked:
  - project_name
  - category_name
  - tribe
  - financial_code
  - it_domain
  - business_line

  Action Required:
  Update dim_projects or source data (stg_jira__projects or SharePoint) to fill missing values.
*/

with projects_with_missing_data as (
    select
        project_id,
        project_key,
        project_name,
        category_name,
        tribe,
        financial_code,
        it_domain,
        business_line,
        product,
        customer,
        -- Flag missing fields
        case when project_name is null or trim(project_name) = '' then 'Missing' else null end as missing_project_name,
        case when category_name is null or trim(category_name) = '' then 'Missing' else null end as missing_category,
        case when tribe is null or trim(tribe) = '' then 'Missing' else null end as missing_tribe,
        case when financial_code is null or trim(financial_code) = '' then 'Missing' else null end as missing_financial_code,
        case when it_domain is null or trim(it_domain) = '' then 'Missing' else null end as missing_it_domain,
        case when business_line is null or trim(business_line) = '' then 'Missing' else null end as missing_business_line,
        _etl_date
    from {{ ref('dim_projects') }}
    where 1=1
        -- Exclude Board category (less critical)
        and coalesce(category_name, '') != 'Board'
)

select
    project_id,
    project_key,
    project_name,
    category_name,
    tribe,
    financial_code,
    it_domain,
    business_line,
    product,
    customer,
    missing_project_name,
    missing_category,
    missing_tribe,
    missing_financial_code,
    missing_it_domain,
    missing_business_line,
    -- Count total missing fields
    (case when missing_project_name is not null then 1 else 0 end +
     case when missing_category is not null then 1 else 0 end +
     case when missing_tribe is not null then 1 else 0 end +
     case when missing_financial_code is not null then 1 else 0 end +
     case when missing_it_domain is not null then 1 else 0 end +
     case when missing_business_line is not null then 1 else 0 end) as total_missing_fields,
    _etl_date
from projects_with_missing_data
where 1=1
    -- At least one critical field is missing
    and (missing_project_name is not null
         or missing_category is not null
         or missing_tribe is not null
         or missing_financial_code is not null
         or missing_it_domain is not null
         or missing_business_line is not null)
order by total_missing_fields desc, project_id
