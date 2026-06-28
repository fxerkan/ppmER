{{
    config(
        materialized="table",
        schema="core",
        tags=["jira", "core", "dim"],
        unique_key="user_name",
        indexes=[
            {"columns": ["user_name"], "unique": True},
            {"columns": ["is_active"]},
        ],
    )
}}

{#
  HR Dimension Table

  Provides HR user information including organizational hierarchy,
  employment status, and team structure.

  Note: This table uses user_name as the primary key since joins are done
  via user_name. For each user_name, we select the most recent active record.
#}
with
    hr_users as (
        select * from {{ ref("stg_jira__hr_users") }}
    ),

    deduplicated as (
        select
            -- User identifiers
            user_name,
            user_display_name,

            -- Organizational hierarchy
            unit_name,
            team_name,
            manager_name,
            deputy_gm_name,
            deputy_gm_upper_unit,

            -- Employment details
            is_active,
            is_manages_team,
            is_outsource_inhouse,
            start_date as employment_start_date,
            exit_date,
            company_info,

            -- Metadata
            created_date,
            _dlt_load_id,
            _dlt_id,

            -- Row number to get the most recent record per user
            row_number() over (
                partition by user_name
                order by
                    is_active desc,  -- Active records first
                    created_date desc,  -- Then most recent
                    _dlt_load_id desc  -- Then latest load
            ) as rn
        from hr_users
        where user_name is not null  -- Exclude null user_names
    ),

    final as (
        select
            -- Primary key
            user_name,

            -- User identifiers
            user_display_name,

            -- Organizational hierarchy
            unit_name,
            team_name,
            manager_name,
            deputy_gm_name,
            deputy_gm_upper_unit,

            -- Employment details
            is_active,
            is_manages_team,
            is_outsource_inhouse,
            employment_start_date,
            exit_date,
            company_info,

            -- Metadata
            created_date,
            _dlt_load_id,
            _dlt_id,
            current_timestamp as _etl_date
        from deduplicated
        where rn = 1  -- Only keep the most recent record per user
    ),

    -- Add "Eski kullanıcı" as a special user record
    eski_kullanici as (
        select
            cast('Eski kullanıcı' as varchar) as user_name,
            cast('Eski kullanıcı' as varchar) as user_display_name,
            cast(null as varchar) as unit_name,
            cast(null as varchar) as team_name,
            cast(null as varchar) as manager_name,
            cast(null as varchar) as deputy_gm_name,
            cast(null as varchar) as deputy_gm_upper_unit,
            cast(false as boolean) as is_active,
            cast(null as varchar) as is_manages_team,
            cast('Inhouse' as varchar) as is_outsource_inhouse,
            cast(null as date) as employment_start_date,
            cast(null as date) as exit_date,
            cast(null as varchar) as company_info,
            cast(current_timestamp as timestamp) as created_date,
            cast(null as varchar) as _dlt_load_id,
            cast(null as varchar) as _dlt_id,
            cast(current_timestamp as timestamp) as _etl_date
    )

select * from final
union all
select * from eski_kullanici
