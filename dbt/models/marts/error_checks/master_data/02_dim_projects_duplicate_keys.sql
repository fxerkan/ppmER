{{
    config(
        materialized="view",
        schema="mart",
        tags=["error_check", "master_data", "data_quality"]
    )
}}

/*
  ERROR CHECK: dim_projects - Duplicate Project Keys

  Description:
  Identifies duplicate project_key or project_id values in dim_projects.
  Duplicates can cause join errors and data inconsistencies.

  Expected Result:
  - Empty result = No duplicates found
  - Rows returned = Duplicate entries that need resolution

  Action Required:
  Investigate source data and merge/remove duplicate entries.
*/

with duplicate_project_ids as (
    select
        project_id,
        count(*) as duplicate_count
    from {{ ref('dim_projects') }}
    group by project_id
    having count(*) > 1
),

duplicate_project_keys as (
    select
        project_key,
        count(*) as duplicate_count
    from {{ ref('dim_projects') }}
    where project_key is not null
    group by project_key
    having count(*) > 1
)

select
    'Duplicate project_id' as error_type,
    p.project_id,
    p.project_key,
    p.project_name,
    p.category_name,
    p.tribe,
    d.duplicate_count,
    p._etl_date
from {{ ref('dim_projects') }} p
inner join duplicate_project_ids d
    on p.project_id = d.project_id

union all

select
    'Duplicate project_key' as error_type,
    p.project_id,
    p.project_key,
    p.project_name,
    p.category_name,
    p.tribe,
    d.duplicate_count,
    p._etl_date
from {{ ref('dim_projects') }} p
inner join duplicate_project_keys d
    on p.project_key = d.project_key

order by error_type, duplicate_count desc
