{{
    config(
        materialized="view",
        schema="staging",
        tags=["jira", "staging"],
        unique_key="user_id",
    )
}}

{#
  Users Staging Model with HR Data Enrichment

  Combines Jira users with HR user data to create a comprehensive
  user dimension with organizational hierarchy and employment details.

  - Base user info from raw_jira.users
  - HR details from raw_jira.hr_users (left joined)
  - Deduplicated to ensure unique users
#}
with
    users_source as (select * from {{ source("raw_jira", "users") }}),

    -- Deduplicate users by keeping the most recent record
    users_deduplicated as (
        select
            *,
            row_number() over (
                partition by account_id order by _dlt_load_id desc
            ) as row_num
        from users_source
    ),

    users_cleaned as (
        select
            account_id as user_id,
            display_name,
            email_address as email,
            active as is_active,
            account_type,
            _dlt_load_id,
            _dlt_id,
            _etl_date
        from users_deduplicated
        where row_num = 1
    ),

    -- Get HR user data, deduplicated by user_account_id (keep most recent)
    hr_users_source as (select * from {{ source("raw_jira", "hr_users") }}),

    hr_users_deduplicated as (
        select
            *,
            row_number() over (
                partition by user_account_id order by created_at desc, _dlt_load_id desc
            ) as row_num
        from hr_users_source
        where user_account_id is not null
    ),

    hr_users_cleaned as (
        select
            user_account_id,
            user_name as hr_user_name,
            name_surname,
            manager_director,
            manager_deputy_gm,
            deputy_gm_upper_unit,
            unit,
            team,
            manages_team,
            outsource_inhouse,
            company_info,
            active_inactive_status as hr_status,
            start_time as employment_start_date,
            issue_key as hr_issue_key,
            created_at as hr_record_created_at
        from hr_users_deduplicated
        where row_num = 1
    ),

    -- Join users with HR data
    users_enriched as (
        select
            -- User identifiers
            u.user_id,
            u.display_name,
            u.email,

            -- Name: prefer HR name_surname if available, else display_name
            coalesce(hr.name_surname, u.display_name) as full_name,

            -- Status: combine both sources
            u.is_active as is_jira_active,
            hr.hr_status,
            case
                when
                    u.is_active = true
                    and (hr.hr_status is null or hr.hr_status = 'Active')
                then true
                when u.is_active = false
                then false
                when hr.hr_status = 'Inactive'
                then false
                else u.is_active
            end as is_active,

            -- Account info
            u.account_type,

            -- HR organizational hierarchy
            hr.unit,
            hr.team,
            hr.manager_director,
            hr.manager_deputy_gm,
            hr.deputy_gm_upper_unit,
            hr.manages_team,

            -- Employment details
            hr.outsource_inhouse,
            hr.company_info,
            hr.employment_start_date,

            -- HR record metadata
            hr.hr_issue_key,
            hr.hr_record_created_at,

            -- Flag to indicate if HR data exists
            case
                when hr.user_account_id is not null then true else false
            end as has_hr_data,

            -- Metadata from users table
            u._dlt_load_id,
            u._dlt_id,
            u._etl_date
        from users_cleaned u
        left join hr_users_cleaned hr on u.user_id = hr.user_account_id
    )

select
    user_id,
    display_name,
    email,
    full_name,
    is_active,
    is_jira_active,
    hr_status,
    account_type,
    -- Organizational hierarchy
    unit,
    team,
    manager_director,
    manager_deputy_gm,
    deputy_gm_upper_unit,
    manages_team,
    -- Employment details
    outsource_inhouse,
    company_info,
    employment_start_date,
    -- Metadata
    has_hr_data,
    -- hr_issue_key,
    -- hr_record_created_at,
    _dlt_load_id,
    _dlt_id,
    _etl_date
from users_enriched
