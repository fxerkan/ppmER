{{
    config(
        materialized="view",
        schema="staging",
        tags=["jira", "staging"],
        unique_key="issue_key",
    )
}}

with
    source as (select * from {{ source("raw_jira", "hr_users") }}),

    renamed as (
        select
            user_account_id,
            user_name,
            name_surname as user_display_name,
            team as team_name,
            unit as unit_name,
            manager_director as manager_name,
            manager_deputy_gm as deputy_gm_name,
            deputy_gm_upper_unit,
            case
                when lower(active_inactive_status) in ('active', 'aktif')
                then true
                when lower(active_inactive_status) in ('inactive', 'inaktif', 'ınaktif')
                then false
                else null
            end as is_active,
            manages_team as is_manages_team,
            outsource_inhouse as is_outsource_inhouse,
            cast(start_time as date) as start_date,
            cast(exit_date as date) as exit_date,
            company_info,
            issue_id,
            issue_key,
            cast(created_at as timestamp) as created_date,
            _dlt_load_id,
            _dlt_id,
            _etl_date
        from source
    )

select *
from renamed
