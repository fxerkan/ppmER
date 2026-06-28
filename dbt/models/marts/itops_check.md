```sql
-- ITOPS DAĞITIM KONTROL - Proje bazında detay
with
raw_data as (
    select
        w.snapshot_period as period
        ,w.trx_date
        ,w.issue_id
        ,w.issue_key
        ,w.worklog_id
        ,w.author_name
        ,w.issue_type as issue_type_name
        ,w.capex_opex
        ,w.project_id
        ,w.project_name
        ,coalesce(w.category_name, 'N/A') as category
        ,coalesce(w.tribe, 'N/A') as tribe
        ,w.customer
        ,w.business_line
        ,w.product
        ,w.hosting as managed_hosting
        ,w.is_outsource_inhouse
        ,w.epic_id
        ,w.epic_name
        ,coalesce(dps.l1_distribution_effort,'No') as l1_distribution_effort
        ,dps.subject_to_l1_distribution as subject_l1_distribution
        ,'No' as l2_distribution_effort
        ,null as subject_l2_distribution
        ,coalesce(dps.app_mgmt_distribution_effort,'No') as app_mgmt_distribution_effort
        ,dps.subject_to_app_mgmt_distribution as subject_app_mgmt_distribution
        ,coalesce(dps.itops_distribution_effort,'No') as itops_distribution_effort
        ,dps.subject_to_itops_distribution as subject_itops_distribution
        ,case
          when extract(year from w.trx_date) = 2025 and lower(w.category_name) in ( 'product', 'maintenance', 'customer' ) then 'Yes'
          when extract(year from w.trx_date) = 2026 then 'No'
          else 'No'
        end as infosec_distribution_effort
        ,case
          when w.project_name = 'Information Security' then 'Distribute'
          else NULL
        end as subject_infosec_distribution
        ,case
          when dps.subject_to_l1_distribution is not null
            or dps.subject_to_app_mgmt_distribution is not null
            or w.project_name = 'Information Security'
            or dps.subject_to_itops_distribution is not null
          then 'Yes'
          else 'No'
        end as is_distribute
        ,round(w.time_spent_person_days,8) as base_effort_raw
        ,case
          when coalesce(w.category_name, '') = 'Board'
          then round(w.time_spent_person_days,8)
          else 0
        end as team_effort
        ,case
          when coalesce(w.category_name, '') != 'Board'
          then round(w.time_spent_person_days,8)
          else 0
        end as tribe_effort
        ,case
          when w.issue_type = 'Operation & L1 Support'
          then round(w.time_spent_person_days,8)
          else 0
        end as operation_l1_support_effort
        ,case
          when w.issue_type = 'Second Level Support (L2)'
          then round(w.time_spent_person_days,8)
          else 0
        end as second_level_l2_support_effort
    from core.fact_worklogs_snapshot w
    left join core.dim_projects_snapshot dps
      on w.snapshot_period = dps.snapshot_period
      and w.project_id = dps.project_id
    where 1 = 1
        and w.trx_date >= '2026-01-01' and w.trx_date < '2027-01-01'
)
,base_data_totals as (
  select *
    , sum(tribe_effort) over (partition by period, tribe) as tribe_effort_total
    , sum(team_effort) over (partition by period, tribe) as team_effort_total
  from raw_data
)
,calc_step__4dist as (
  select *
    , base_effort_raw as base_effort_raw__debug
    , (operation_l1_support_effort+second_level_l2_support_effort) as operation_l1_l2_effort
    , case
        when category <> 'Board'
        then base_effort_raw - (operation_l1_support_effort+second_level_l2_support_effort)
        else 0
      end as base_effort
  from base_data_totals
)
,calc_step1 as (
  select *
    , (operation_l1_support_effort+second_level_l2_support_effort) as operation_l1_l2_effort
    , case
        when category <> 'Board'
        then base_effort_raw - (operation_l1_support_effort+second_level_l2_support_effort)
        else 0
      end as base_effort
  from base_data_totals
  where is_distribute = 'No'
)
,calc_step2 as (
  select *
    ,sum(base_effort) over (partition by period, tribe) as base_effort_total
  from calc_step1
)
,calc_step3 as (
  select *
    ,team_effort_total as team_effort_total__debug
    ,coalesce(round((base_effort / nullif(base_effort_total,0)),10) ,0) as team_effort_weight
    ,coalesce( round(team_effort_total * round((base_effort / nullif(base_effort_total,0)),10) ,8) ,0) as team_effort_normalized
  from calc_step2
)
,calc_step4 as (
  select *
    ,case
      when coalesce(is_distribute,'No') = 'No' then base_effort + team_effort_normalized
      else 0
    end as dev_tribe_effort
    ,operation_l1_support_effort as enterprise_support_effort
    ,second_level_l2_support_effort as app_mngmt_effort
    ,0 as infra_system_support_effort
  from calc_step3
)
,calc_step5 as (
  select *
    ,(dev_tribe_effort + enterprise_support_effort + app_mngmt_effort + infra_system_support_effort) as final_effort
  from calc_step4
)
,itops_base as (
    select
        period, tribe, project_id, project_name, is_outsource_inhouse, capex_opex, max(category) as category
      , 'ITOPS' as distribute_from
      , itops_distribution_effort as yes_no
      , sum(dev_tribe_effort) as dev_tribe_effort__itops
    from calc_step5
    where itops_distribution_effort = 'Yes'
    group by period, tribe, project_id, project_name, is_outsource_inhouse, capex_opex, itops_distribution_effort
)
,itops_agg as (
    select
      *
      ,sum(dev_tribe_effort__itops) OVER (partition by period, is_outsource_inhouse, capex_opex) as dev_tribe_effort__itops_total
      ,round(dev_tribe_effort__itops / nullif(sum(dev_tribe_effort__itops) OVER (partition by period, is_outsource_inhouse, capex_opex),0) ,8) as dev_tribe_effort__itops_weight
    from itops_base
)
,itops_dist_step1 as (
    select
      period, project_id, project_name, category, tribe, is_outsource_inhouse, capex_opex
      ,sum(base_effort_raw) as base_effort__itops
      ,sum(base_effort) as base_effort__itops2
      ,'ITOPS' as distribute_subject
    from calc_step__4dist
    where 1=1
      and subject_itops_distribution is not null
      and issue_type_name != 'User Support'
    group by period, project_id, project_name, category, tribe, is_outsource_inhouse, capex_opex
)
,itops_dist_step2 as (
    select d1.period
      , '-500' || d2.project_id as project_id
      , d2.project_name as project_name
      , d1.project_name as source_project_name
      , d2.category, d1.tribe, d1.is_outsource_inhouse, d1.capex_opex
      , d1.base_effort__itops as dist_base_effort
      , d2.distribute_from
      , d2.yes_no
      , d2.dev_tribe_effort__itops as dist_dev_tribe_effort
      , d2.dev_tribe_effort__itops_weight as dist_weight
      , round(d1.base_effort__itops * d2.dev_tribe_effort__itops_weight ,8) as distributed_effort
      , 'Yes' as is_distributed_row
    from itops_dist_step1 d1
    inner join itops_agg d2
      on d1.period = d2.period
      and d1.is_outsource_inhouse = d2.is_outsource_inhouse
      and d1.capex_opex = d2.capex_opex
    where d2.yes_no = 'Yes'
)
select period
  , project_name
  , source_project_name
  , tribe
  , is_outsource_inhouse
  , capex_opex
  , dist_base_effort as kaynak_efor
  , dist_weight
  , distributed_effort as dagitilan_efor
from itops_dist_step2
order by period, is_outsource_inhouse, capex_opex, project_name, source_project_name
```
