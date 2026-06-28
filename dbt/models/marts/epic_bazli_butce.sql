{{ config(
    materialized="table",
    schema="mart",
    tags=["jira", "mart", "datamart"],
    enabled=false
) }}

with proje_butce as (
  select
    source_issue_key, link_type_name
    ,target_issue_key, target_summary
    ,pbb."key" as pbb_key
    ,pbb.summary as pbb_summary
    ,pbb.status_name
    ,pbb.status_category
    ,pbb.budget_person_days
    ,pbb.budgeting_year
    ,'N/A' as budgeting_type
  from issue_links il
  left join pbb_issues pbb
    on il.target_issue_key = pbb."key"
  where 1=1
  and il.link_type_name = 'Bütçe'
  --and source_issue_key =  'AP-3894'
  )
select 
  ef.*
  ,i.issue_key as epic_key
  ,pb.*
from mart.fact_distributed_efforts_2026 ef
  left join core.dim_issues i 
    on ef.epic_id = i.issue_id
  left join proje_butce pb on pb.source_issue_key = i.issue_key
  where 1=1
  and ef.epic_id = '302290'
