{{ config(
    materialized="table",
    schema="mart",
    tags=["jira", "mart", "datamart"]
) }} 
-- 2026 Effort Distribution - NEW 20260129
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
        ,case
          when w.project_name = 'IT_OPERATION' and w.issue_type = 'User Support'
          then 'IT_OPERATION (Kullanıcı Destek)'
          else w.project_name
        end as project_name
        ,coalesce(w.category_name, 'N/A') as category
        ,coalesce(w.tribe, 'N/A') as tribe
        ,w.customer
        ,coalesce(dps.it_domain, 'N/A') as it_domain
        ,w.business_line
        ,w.product
        ,w.hosting as managed_hosting
        ,dps.financial_code
        ,w.is_outsource_inhouse
        ,w.epic_id
        ,w.epic_name
        ,coalesce(dps.l1_distribution_effort,'No') as l1_distribution_effort
        ,dps.subject_to_l1_distribution as subject_l1_distribution
----FX Todo - bu alanlar project_properties de yok, eklenmeli mi
        --,dps.subject_to_l2_distribution as subject_to_l2_distribution
        ,'No' as l2_distribution_effort
        ,null as subject_l2_distribution
        ,coalesce(dps.app_mgmt_distribution_effort,'No') as app_mgmt_distribution_effort
        ,dps.subject_to_app_mgmt_distribution as subject_app_mgmt_distribution
        ,coalesce(dps.itops_distribution_effort,'No') as itops_distribution_effort
        ,dps.subject_to_itops_distribution as subject_itops_distribution
----FX Todo - bu alanlar project_properties de yok, eklenmeli mi
        --,dps.subject_to_infosec_distribution as subject_infosec_distribution
        ,case 
          when extract(year from w.trx_date) = 2025 and lower(w.category_name) in ( 'product', 'maintenance', 'customer' ) then 'Yes'
          when extract(year from w.trx_date) = 2026 then 'No' --2026 da dağıtılmayacak
          else 'No'
        end as infosec_distribution_effort
        ,NULL as subject_infosec_distribution --20260212 InfoSec şimdilik dağıtılmayacak, proje doğrudan gelecek
        ,case
          when dps.subject_to_l1_distribution is not null
            --or dps.subject_to_l2_distribution is not null
            or dps.subject_to_app_mgmt_distribution is not null
            --or w.project_name = 'Information Security'  --20260212 InfoSec şimdilik dağıtılmayacak
            or dps.subject_to_itops_distribution is not null
          then 'Yes'
          else 'No'
        end as is_distribute
        ,case
            when w.project_id = '10035' then 'Alt Yapi ve Güvenlik'
            when w.project_id = '10347' then 'Alt Yapi ve Güvenlik'
            when w.project_id = '10386' then 'L1' --SERVICE_DESK_L1
            when w.project_id = '10457' then 'L2'
            when w.project_id = '10822' then 'Information Security'
            when w.project_id in ('10311', '10184', '10169', '10522', '10521') then 'Uygulama Yönetimi'
            when w.project_name ilike '%TEAM%' then 'Board'
            else 'Diğer'
        end as effort_type
        ,round(w.time_spent_person_days,8) as base_effort_raw
        /*
        case 
          when w.issue_type in ('Operation & L1 Support', 'Second Level Support (L2)') --Ham Efor - (Operation L1+Operation L2)
          then -1 * round(w.time_spent_person_days,8)
          else round(w.time_spent_person_days,8)
        end as base_effort
        */
        --round(w.time_spent_person_days,8) as base_effort,
        ,case
            when
                w.issue_type in (
                    'Administrative Activities',
                    'Day Off',
                    'External Education',
                    'Internal Education',
                    'Orientation',
                    'Information Security Support',
                    'SQL Support',
                    'System Support'
                )
            then round(w.time_spent_person_days, 8)
            else 0
        end as exclude_effort
        --Team Effort
        ,case 
          when coalesce(w.category_name, '') = 'Board' 
          then round(w.time_spent_person_days,8)  
          else 0 
        end as team_effort
        --Tribe Effort
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
        ,case 
          when w.issue_type = 'Operation & Support (L3)'
          then round(w.time_spent_person_days,8)  
          else 0
        end as operation_l3_support_effort
    from {{ ref('fact_worklogs_snapshot') }} w
    left join {{ ref('dim_projects_snapshot') }} dps
      on w.snapshot_period = dps.snapshot_period
      and w.project_id = dps.project_id
    where 1 = 1
----FX Todo - Tarih filtresi 2026 yılına göre değiştirilecek, şimdilik 2025 verisi üzerinden test amaçlı yapıldı !!!
        and w.trx_date >= '2026-01-01' and w.trx_date < '2027-01-01'
        --and w.is_period_locked = true
----debug
        --and w.snapshot_period = '2025-01'
        --and w.trx_date = '2025-01-01'
        --and w.project_name LIKE '%ACQUIRING_NEOPAY%'
        --and w.tribe in ( 'Transit' )
      /* and (
            w.tribe in (w.tribe)
            --w.tribe in ( 'PF','Wallet','Transit' )  ----Tribe=Transit >> 'DGTRANSIT_VISA_Maintenance', 'TRANSIT_TRKART_PTT_Maintenance' ,'HERMES TEAM'
            --w.tribe = 'PF'
            or w.project_name in ( 
                                'SERVICE_DESK_L1' --L1
                                --App Mgmt
                                  ,'SHADOW TEAM','SHADOW TALEP HAVUZU','SHADOW_OPERATION','Shadow Test Paket Yönetimi','SHADOW DEVOPS','SHADOW PM TEST','HUB HEROES_SLS_L2','Hub Heroes - Uygulama Yönetimi','Hub Heroes - Devops'
                                ,'IT_OPERATION'
                                ,'Information Security'
                               )
            )
      */
)
--select * from raw_data   order by trx_date
,base_data_totals as
(
  select * 
    , sum(tribe_effort) over (partition by period, tribe) as tribe_effort_total
    , sum(team_effort) over (partition by period, tribe) as team_effort_total
  from raw_data
)
--select * from base_data_totals
,calc_step__4dist as
(
  select *
    , base_effort_raw as base_effort_raw__debug
    , (operation_l1_support_effort+second_level_l2_support_effort) as operation_l1_l2_effort
    , case 
        when category <> 'Board' --Takım eforları hariç
        then base_effort_raw - (operation_l1_support_effort+second_level_l2_support_effort)
        else 0 
      end as base_effort
  from base_data_totals
  where 1=1
  --and is_distribute = 'Yes'
)
,calc_step1 as
(
  select *
    , base_effort_raw as base_effort_raw__debug
    , (operation_l1_support_effort+second_level_l2_support_effort) as operation_l1_l2_effort
    , case 
        when category <> 'Board' --Takım eforları hariç
        then base_effort_raw - (operation_l1_support_effort+second_level_l2_support_effort)
        else 0 
      end as base_effort
  from base_data_totals
  where 1=1
  and is_distribute = 'No' --Dağıtılmayacak gerçek proje eforlarını baz alıp, bunların üzerine sadece takım eforları eklenecek
)
--select * from calc_step1 
,calc_step2 as
(
  select *
    ,sum(base_effort) over (partition by period, tribe) as base_effort_total --FX DONE tribe bazında partitioning eklendi
  --,project_name
  from calc_step1
)
--select * from calc_step2
,calc_step3 as 
(
  --Takım eforları normalize edilir
  select *
    ,team_effort_total as team_effort_total__debug
    --,base_effort_total as base_effort_total__debug
    ,coalesce(round((base_effort / nullif(base_effort_total,0)),10) ,0) as team_effort_weight
  --,case when team_effort_total <> 0 then round((base_effort / base_effort_total),8) else 0 end as team_effort_weight
    ,coalesce( round(team_effort_total * round((base_effort / nullif(base_effort_total,0)),10) ,8) ,0) as team_effort_normalized
  from calc_step2
)
--select * from calc_step3 where base_effort_total = 0
/*  ----debug summary
select period, tribe, project_name
  , sum(base_effort_raw) base_effort_raw
  , sum(operation_l1_support_effort) as operation_l1_support_effort
  , sum(second_level_l2_support_effort) as second_level_l2_support_effort
  , sum(operation_l1_support_effort) + sum(second_level_l2_support_effort) as l1_l2_effort
  , sum(base_effort) base_effort
  , max(base_effort_total) base_effort_total, max(team_effort_total__debug) team_effort_total__debug
  , sum(team_effort_weight) team_effort_weight, sum(team_effort_normalized) team_effort_normalized
from calc_step3
group by period, tribe, rollup( project_name)
order by 1,2 
*/
,calc_step4 as 
(
  select *
    ,case 
      when coalesce(is_distribute,'No') = 'No' then base_effort + team_effort_normalized 
      else 0
    end as dev_tribe_effort
    ,operation_l1_support_effort as enterprise_support_effort
    ,second_level_l2_support_effort as app_mngmt_effort
  --FX Todo - bu
    ,0 as infra_system_support_effort
  from calc_step3
)
--select * from calc_step4
/* ----debug
  select period, tribe, project_name
  , sum(base_effort_raw) as base_effort_raw
  , sum(base_effort) as base_effort
  , sum(team_effort) as team_effort
  , sum(team_effort_normalized) as team_effort_normalized
  , sum(dev_tribe_effort) as dev_tribe_effort
  ,sum(enterprise_support_effort) as enterprise_support_effort
  ,sum(app_mngmt_effort) as app_mngmt_effort
  from calc_step4
  group by period, tribe, rollup( project_name)
*/
,calc_step5 as 
(
  select *
    ,(dev_tribe_effort + enterprise_support_effort + app_mngmt_effort + infra_system_support_effort) as final_effort
  from calc_step4
)
--select * from calc_step5
/* ----debug
select 
    period
  , tribe
  , project_name
    --, is_distribute
  --,issue_type_name
  , sum(base_effort_raw) as base_effort_raw
  , sum(operation_l1_support_effort) as operation_l1_support_effort, sum(second_level_l2_support_effort) as second_level_l2_support_effort
  , sum(base_effort) as base_effort
  , sum(team_effort_normalized) as team_effort_normalized
  , sum(dev_tribe_effort) as dev_tribe_effort, sum(enterprise_support_effort) as enterprise_support_effort, sum(app_mngmt_effort) as app_mngmt_effort, sum(infra_system_support_effort) as infra_system_support_effort
  , sum(final_effort) as final_effort
from calc_step5
group by period, tribe, rollup(project_name)
    --,  is_distribute
  --group by period, project_name, is_distribute
  --,issue_type_name
--order by period, tribe, project_name
  --,issue_type_name
*/
-- ***** L1 Distribution ***** --
  --20260205 ITOPS ile aynı yöntem: is_outsource_inhouse ve capex_opex bazında partitioning
  ,l1_base as
  (
    --L1=EVET olarak işaretli olan worklogların toplam eforunu bulmak için
    --20260216 proje başına tek satır: boyut ve detay alanları MAX() ile alınıyor. Amac tek satır proje elde etmek.
    select
        period, project_id, project_name
      , max(tribe) as tribe, max(category) as category
      , max(customer) as customer, max(it_domain) as it_domain
      , max(business_line) as business_line, max(product) as product
      , max(managed_hosting) as managed_hosting, max(financial_code) as financial_code
      , 'L1' as distribute_from
      , l1_distribution_effort as yes_no
      , sum(dev_tribe_effort) as dev_tribe_effort__l1
    from calc_step5
    where lower(l1_distribution_effort) = 'yes'
    group by period, project_id, project_name, l1_distribution_effort
  )
  --select * from l1_base
  ,l1_agg as
  (
    select
      *
      ,sum(dev_tribe_effort__l1) OVER (partition by period) as dev_tribe_effort__l1_total  --ilgili dönem bazında toplam efor (tüm boyutlar dahil)
      ,round(dev_tribe_effort__l1 / nullif(sum(dev_tribe_effort__l1) OVER (partition by period),0) ,8) as dev_tribe_effort__l1_weight
    from l1_base
  )
  --select * from l1_agg
  ,l1_dist_step1 as
  (
    --Dağıtılacak (worklog kayıtlarının altına ayrıca birer satır olarak eklenecek) kayıtlara ait eforlar
    select
      period,  project_id, project_name, category, tribe, is_outsource_inhouse, capex_opex
      --,max(customer) as customer, max(it_domain) as it_domain, max(business_line) as business_line, max(product) as product, max(managed_hosting) as managed_hosting
      ,sum(base_effort_raw) as base_effort__l1
      --,sum(base_effort) as base_effort2__l1
      ,'L1' as distribute_subject
    --from base_data_totals 20260129 erkanc
    from calc_step__4dist
    where 1=1
    and subject_l1_distribution is not null  --"L1 Distribution" içerisinde dağıtılacak olarak işaretlenen projeler
    --and subject_itops_distribution is not null
    group by period, project_id, project_name, category, tribe, is_outsource_inhouse, capex_opex
  )
 -- select * from l1_dist_step1
  ,l1_dist_step2 as
  (
    --Dağıtılacak satırlar (projeler) her birisi L1=EVET olarak işaretlenen her bir proje bazında çoklanıp/ağırlıklandırılıp
    --EVET işaretlenen Proje kaydı olarak tekrar oluşturulur
    --20260205 is_outsource_inhouse ve capex_opex bazında eşleşme ve weight hesabı eklendi (ITOPS ile aynı yöntem)
    select d1.period
      , '-100' || d2.project_id as project_id
      , d2.project_name as project_name
      , d1.project_name as source_project_name
      , d2.category, d1.tribe, d1.is_outsource_inhouse, d1.capex_opex
      , d2.customer, d2.it_domain, d2.business_line, d2.product, d2.managed_hosting, d2.financial_code
      , d1.base_effort__l1 as dist_base_effort
      , d2.distribute_from
      , d2.yes_no
      , d2.dev_tribe_effort__l1 as dist_dev_tribe_effort
      , d2.dev_tribe_effort__l1_weight as dist_weight
      , round(d1.base_effort__l1 * d2.dev_tribe_effort__l1_weight,8) as distributed_effort
      , 'Yes' as is_distributed_row
    from l1_dist_step1 d1
    inner join l1_agg d2
      on d1.period = d2.period
      --20260216 is_outsource_inhouse ve capex_opex eşleşmesi kaldırıldı: her proje tüm boyutlardan dağıtım alacak
    where d2.yes_no = 'Yes'
  )
  --select * from l1_dist_step2
  --where project_name ='DGTRANSIT_VISA_Maintenance'  
  --select * into mart.fact_distributed_efforts_2026_new__l1 from l1_dist_step2
  /* select period, tribe, project_name
    ,max(base_effort__l1) base_effort__l1
    ,sum(dev_tribe_effort__l1) dev_tribe_effort
    ,sum(dist_weight) dist_weight
    ,sum(distributed_effort) distributed_effort
  from l1_dist_step2
  group by period, tribe, rollup(project_name)
  */
-- ***** L2 Distribution ***** --
  --20260205 ITOPS ile aynı yöntem: is_outsource_inhouse ve capex_opex bazında partitioning
  ,l2_base as
  (
    --L2=EVET olarak işaretli olan worklogların toplam eforunu bulmak için
    --20260216 proje başına tek satır: boyut ve detay alanları MAX() ile alınıyor.Amac tek satır proje elde etmek.
    select
        period, project_id, project_name
      , max(tribe) as tribe, max(category) as category
      , max(customer) as customer, max(it_domain) as it_domain
      , max(business_line) as business_line, max(product) as product
      , max(managed_hosting) as managed_hosting, max(financial_code) as financial_code
      , 'L2' as distribute_from
      , l2_distribution_effort as yes_no
      , sum(dev_tribe_effort) as dev_tribe_effort__l2
    from calc_step5
    where lower(l2_distribution_effort) = 'yes'
    group by period, project_id, project_name, l2_distribution_effort
  )
  --select * from l2_base
  ,l2_agg as
  (
    select
      *
      ,sum(dev_tribe_effort__l2) OVER (partition by period) as dev_tribe_effort__l2_total  --ilgili dönem bazında toplam efor (tüm boyutlar dahil)
      ,round(dev_tribe_effort__l2 / nullif(sum(dev_tribe_effort__l2) OVER (partition by period),0) ,8) as dev_tribe_effort__l2_weight
    from l2_base
  )
  --select * from l2_agg
  ,l2_dist_step1 as
  (
    --Dağıtılacak (worklog kayıtlarının altına ayrıca birer satır olarak eklenecek) kayıtlara ait eforlar
    select
      period,  project_id, project_name, category, tribe, is_outsource_inhouse, capex_opex
     -- ,max(customer) as customer, max(it_domain) as it_domain, max(business_line) as business_line, max(product) as product, max(managed_hosting) as managed_hosting, max(financial_code) as financial_code
      ,sum(base_effort_raw) as base_effort__l2
      --,sum(base_effort) as base_effort2__l2
      ,'L2' as distribute_subject
    --from base_data_totals 20260129 erkanc
    from calc_step__4dist
    where 1=1
    and subject_l2_distribution is not null  --"L2 Distribution" içerisinde dağıtılacak olarak işaretlenen projeler
    --and subject_itops_distribution is not null
    group by period, project_id, project_name, category, tribe, is_outsource_inhouse, capex_opex
  )
  --select * from l2_dist_step1
  ,l2_dist_step2 as
  (
    --Dağıtılacak satırlar (projeler) her birisi L2=EVET olarak işaretlenen her bir proje bazında çoklanıp/ağırlıklandırılıp
    --EVET işaretlenen Proje kaydı olarak tekrar oluşturulur
    --20260205 is_outsource_inhouse ve capex_opex bazında eşleşme ve weight hesabı eklendi (ITOPS ile aynı yöntem)
    select d1.period
      , '-200' || d2.project_id as project_id
      , d2.project_name as project_name
      , d1.project_name as source_project_name
      , d2.category, d1.tribe, d1.is_outsource_inhouse, d1.capex_opex
      , d2.customer, d2.it_domain, d2.business_line, d2.product, d2.managed_hosting, d2.financial_code
      , d1.base_effort__l2 as dist_base_effort
      , d2.distribute_from
      , d2.yes_no
      , d2.dev_tribe_effort__l2 as dist_dev_tribe_effort
      , d2.dev_tribe_effort__l2_weight as dist_weight
      , round(d1.base_effort__l2 * d2.dev_tribe_effort__l2_weight,8) as distributed_effort
      , 'Yes' as is_distributed_row
    from l2_dist_step1 d1
    inner join l2_agg d2
      on d1.period = d2.period
      --20260216 boyut eşleşmesi kaldırıldı: her proje tüm boyutlardan dağıtım alacak
    where d2.yes_no = 'Yes'
  )
  --select * from l2_dist_step2
-- ***** App Management Distribution ***** --
  --20260205 ITOPS ile aynı yöntem: is_outsource_inhouse ve capex_opex bazında partitioning
  ,app_management_base as
  (
    --App Management=EVET olarak işaretli olan worklogların toplam eforunu bulmak için
    --20260216 proje başına tek satır: boyut ve detay alanları MAX() ile alınıyor.Amac tek satır proje elde etmek.
    select
        period, project_id, project_name
      , max(tribe) as tribe, max(category) as category
      , max(customer) as customer, max(it_domain) as it_domain
      , max(business_line) as business_line, max(product) as product
      , max(managed_hosting) as managed_hosting, max(financial_code) as financial_code
      , 'App Management' as distribute_from
      , app_mgmt_distribution_effort as yes_no
      , sum(dev_tribe_effort) as dev_tribe_effort__app_mgmt
    from calc_step5
    where 1=1
    and app_mgmt_distribution_effort = 'Yes'
    group by period, project_id, project_name, app_mgmt_distribution_effort
  )
  --select * from app_management_base
  ,app_management_agg as
  (
    select
      *
      ,sum(dev_tribe_effort__app_mgmt) OVER (partition by period) as dev_tribe_effort__app_mgmt_total  --ilgili dönem bazında toplam efor (tüm boyutlar dahil)
      ,round(dev_tribe_effort__app_mgmt / nullif(sum(dev_tribe_effort__app_mgmt) OVER (partition by period),0) ,8) as dev_tribe_effort__app_mgmt_weight
    from app_management_base
  )
  --select * from app_management_agg
  --select sum(dev_tribe_effort__app_mgmt) as dev_tribe_effort, max(dev_tribe_effort__app_mgmt_total) as dev_tribe_effort_total, sum(dev_tribe_effort__app_mgmt_weight) weight from app_management_agg
  --PF+Wallet dev_tribe_effort_total = 661.06652603, Total Weight = 1,  PF_AKODE Wiegtht = 0.25249966 , WALLET_DGPARA_Maintenance Wieght = 0.21054907
   --PF+Wallet+Transit dev_tribe_effort_total = 987.08735883, PF_AKODE Wiegtht = 0.16910263 , WALLET_DGPARA_Maintenance Wieght = 0.14100772, TRANSIT_TRKART_PTT_Maintenance Weight = 0.2911138
  ,app_management_dist_step1 as
  (
    --Dağıtılacak (worklog kayıtlarının altına ayrıca birer satır olarak eklenecek) kayıtlara ait eforlar
    select
      period, project_id, project_name, category, tribe, is_outsource_inhouse, capex_opex
      --,max(customer) as customer, max(it_domain) as it_domain, max(business_line) as business_line, max(product) as product, max(managed_hosting) as managed_hosting, max(financial_code) as financial_code
      ,sum(base_effort_raw) as base_effort__app_mgmt
      ,sum(base_effort) as base_effort__app_mgmt2
      ,'App Management' as distribute_subject
    --from base_data_totals --20260129 erkanc - base_totals tablosundan değilde distribution için oluşturulan calc_step__4dist tablosundan alacak şekilde düzenlendi
    --bu sayede base_effort içerisinde (operation_l1+second_level_l2) eforları hariç efor ve bir de Board olarak işaretlenmiş dağıtıma konu olan proje eforlarının tekrardan eklenmesi önlenmiş oluyor
    --bakınız "HUB HEROES_SLS_L2" - category = Board
    from calc_step__4dist
    where 1=1
    and subject_app_mgmt_distribution is not null  --"App Management Distribution" içerisinde dağıtılacak olarak işaretlenen projeler
    group by period, project_id, project_name, category, tribe, is_outsource_inhouse, capex_opex
  )
   --select * from app_management_dist_step1
   --select sum(base_effort__app_mgmt) as base_effort__app_mgmt, sum(base_effort__app_mgmt2) as base_effort__app_mgmt2 from app_management_dist_step1
  -- base_effort__app_mgmt = 282.13750003 , base_effort__app_mgmt2	= 236.90833336
  ,app_management_dist_step2 as
  (
    --Dağıtılacak satırlar (projeler) her birisi App Management=EVET olarak işaretlenen her bir proje bazında çoklanıp/ağırlıklandırılıp
    --EVET işaretlenen Proje kaydı olarak tekrar oluşturulur
    --20260205 is_outsource_inhouse ve capex_opex bazında eşleşme ve weight hesabı eklendi (ITOPS ile aynı yöntem)
    select d1.period
      , '-300' || d2.project_id as project_id
      , d2.project_name as project_name
      , d1.project_name as source_project_name
      , d2.category, d1.tribe, d1.is_outsource_inhouse, d1.capex_opex
      , d2.customer, d2.it_domain, d2.business_line, d2.product, d2.managed_hosting, d2.financial_code
      , d1.base_effort__app_mgmt as dist_base_effort
      , d2.distribute_from, d2.yes_no
      , d2.dev_tribe_effort__app_mgmt as dist_dev_tribe_effort
      , d2.dev_tribe_effort__app_mgmt_weight as dist_weight
      , round(d1.base_effort__app_mgmt * d2.dev_tribe_effort__app_mgmt_weight ,8) as distributed_effort
      , 'Yes' as is_distributed_row
    from app_management_dist_step1 d1
    inner join app_management_agg d2
      on d1.period = d2.period
      --20260216 boyut eşleşmesi kaldırıldı: her proje tüm boyutlardan dağıtım alacak
    where d2.yes_no = 'Yes'
  )
  --select * from app_management_dist_step2 
  --where project_name ='DGTRANSIT_VISA_Maintenance'
  --select * into mart.fact_distributed_efforts_2026_new__app_mgmt from app_management_dist_step2
  /* select period
    , tribe
    , project_name
    --,max(base_effort__app_mgmt) base_effort
    --,sum(dev_tribe_effort__app_mgmt) dev_tribe_effort
    ,max(base_effort) base_effort
    ,sum(dev_tribe_effort) dev_tribe_effort
    ,max(dist_weight) dist_weight
    ,sum(distributed_effort) distributed_effort
    --,max(base_effort2) base_effort2
    --,sum(distributed_effort2) distributed_effort2
  from app_management_dist_step2
  --where project_name = 'PF_AKODE_Maintenance'
  group by period
    , tribe
    --, rollup(project_name)
    , project_name
  */
-- ***** InfoSec Distribution ***** --
  --20260205 ITOPS ile aynı yöntem: is_outsource_inhouse ve capex_opex bazında partitioning
  ,infosec_base as
  (
    --Info Sec Distribution=EVET olarak işaretli olan worklogların toplam eforunu bulmak için
    --20260216 proje başına tek satır: boyut ve detay alanları MAX() ile alınıyor.Amac tek satır proje elde etmek.
    select
        period, project_id, project_name
      , max(tribe) as tribe, max(category) as category
      , max(customer) as customer, max(it_domain) as it_domain
      , max(business_line) as business_line, max(product) as product
      , max(managed_hosting) as managed_hosting, max(financial_code) as financial_code
      , 'InfoSec' as distribute_from
      , infosec_distribution_effort as yes_no
      , sum(dev_tribe_effort) as dev_tribe_effort__infosec
    from calc_step5
    where infosec_distribution_effort = 'Yes'
    group by period, project_id, project_name, infosec_distribution_effort
  )
  --select * from infosec_base
  ,infosec_agg as
  (
    select
      *
      ,sum(dev_tribe_effort__infosec) OVER (partition by period) as dev_tribe_effort__infosec_total  --ilgili dönem bazında toplam efor (tüm boyutlar dahil)
      ,round(dev_tribe_effort__infosec / nullif(sum(dev_tribe_effort__infosec) OVER (partition by period),0) ,8) as dev_tribe_effort__infosec_weight
    from infosec_base
  )
  --select * from infosec_agg
  ,infosec_dist_step1 as
  (
    --Dağıtılacak (worklog kayıtlarının altına ayrıca birer satır olarak eklenecek) kayıtlara ait eforlar
    select
      period, project_id, project_name, category, tribe, is_outsource_inhouse, capex_opex
      --,max(customer) as customer, max(it_domain) as it_domain, max(business_line) as business_line, max(product) as product, max(managed_hosting) as managed_hosting, max(financial_code) as financial_code
      ,sum(base_effort_raw) as base_effort__infosec
      ,sum(base_effort) as base_effort__infosec2
      ,'InfoSec' as distribute_subject
    --from base_data_totals 20260129
    from calc_step__4dist
    where 1=1
    and subject_infosec_distribution is not null  --"InfoSec Distribution" içerisinde dağıtılacak olarak işaretlenen projeler
    group by period, project_id, project_name, category, tribe, is_outsource_inhouse, capex_opex
  )
  --select * from infosec_dist_step1
  ,infosec_dist_step2 as
  (
    --Dağıtılacak satırlar (projeler) her birisi InfoSec=EVET olarak işaretlenen her bir proje bazında çoklanıp/ağırlıklandırılıp
    --EVET işaretlenen Proje kaydı olarak tekrar oluşturulur
    --20260205 is_outsource_inhouse ve capex_opex bazında eşleşme ve weight hesabı eklendi (ITOPS ile aynı yöntem)
    select d1.period
      , '-400' || d2.project_id as project_id
      , d2.project_name as project_name
      , d1.project_name as source_project_name
      , d2.category, d1.tribe, d1.is_outsource_inhouse, d1.capex_opex
      , d2.customer, d2.it_domain, d2.business_line, d2.product, d2.managed_hosting, d2.financial_code
      , d1.base_effort__infosec as dist_base_effort
      , d2.distribute_from
      , d2.yes_no
      , d2.dev_tribe_effort__infosec as dist_dev_tribe_effort
      , d2.dev_tribe_effort__infosec_weight as dist_weight
      , round(d1.base_effort__infosec * d2.dev_tribe_effort__infosec_weight ,8) as distributed_effort
      , 'Yes' as is_distributed_row
    from infosec_dist_step1 d1
    inner join infosec_agg d2
      on d1.period = d2.period
      --20260216 boyut eşleşmesi kaldırıldı: her proje tüm boyutlardan dağıtım alacak
    where d2.yes_no = 'Yes'
  )
 --select * from infosec_dist_step2
 -- where project_name ='DGTRANSIT_VISA_Maintenance'
  --select * into mart.fact_distributed_efforts_2026_new__infosec from infosec_dist_step2
-- ***** ITOPS Distribution ***** --
  ,itops_base as
  (
    --ITOPS Distribution=EVET olarak işaretli olan worklogların toplam eforunu bulmak için
    --20260216 proje başına tek satır: boyut ve detay alanları MAX() ile alınıyor.Amac tek satır proje elde etmek.
    select
        period, project_id, project_name
      , max(tribe) as tribe, max(category) as category
      , max(customer) as customer, max(it_domain) as it_domain
      , max(business_line) as business_line, max(product) as product
      , max(managed_hosting) as managed_hosting, max(financial_code) as financial_code
      , 'ITOPS' as distribute_from
      , itops_distribution_effort as yes_no
      , sum(dev_tribe_effort) as dev_tribe_effort__itops
    from calc_step5
    where itops_distribution_effort = 'Yes'
    group by period, project_id, project_name, itops_distribution_effort
  )
  --select * from itops_base
  ,itops_agg as
  (
    select
      *
      ,sum(dev_tribe_effort__itops) OVER (partition by period) as dev_tribe_effort__itops_total  --ilgili dönem bazında toplam efor (tüm boyutlar dahil)
      ,round(dev_tribe_effort__itops / nullif(sum(dev_tribe_effort__itops) OVER (partition by period),0) ,8) as dev_tribe_effort__itops_weight
    from itops_base
  )
  --select * from itops_agg
  ,itops_dist_step1 as
  (
    --Dağıtılacak (worklog kayıtlarının altına ayrıca birer satır olarak eklenecek) kayıtlara ait eforlar
    select
      period, project_id, project_name, category, tribe, is_outsource_inhouse, capex_opex
     -- ,max(customer) as customer, max(it_domain) as it_domain, max(business_line) as business_line, max(product) as product, max(managed_hosting) as managed_hosting, max(financial_code) as financial_code
      ,sum(base_effort_raw) as base_effort__itops
      ,sum(base_effort) as base_effort__itops2
      ,'ITOPS' as distribute_subject
    --from base_data_totals
    from calc_step__4dist
    where 1=1
    and subject_itops_distribution is not null  --"ITOPS Distribution" içerisinde dağıtılacak olarak işaretlenen projeler
    and issue_type_name != 'User Support'
    group by period, project_id, project_name, category, tribe, is_outsource_inhouse, capex_opex
  )
  --select * from itops_dist_step1
  ,itops_dist_step2 as
  (
    --Dağıtılacak satırlar (projeler) her birisi ITOPS Distribution=EVET olarak işaretlenen her bir proje bazında çoklanıp/ağırlıklandırılıp
    --EVET işaretlenen Proje kaydı olarak tekrar oluşturulur
    --20260204 is_outsource_inhouse ve capex_opex bazında eşleşme ve weight hesabı eklendi
    select d1.period
      , '-500' || d2.project_id as project_id
      , d2.project_name as project_name
      , d1.project_name as source_project_name
      , d2.category, d1.tribe, d1.is_outsource_inhouse, d1.capex_opex
      , d2.customer, d2.it_domain, d2.business_line, d2.product, d2.managed_hosting, d2.financial_code
      , d1.base_effort__itops as dist_base_effort
      --, d1.base_effort__itops2 as dist_base_effort2
      , d2.distribute_from
      , d2.yes_no
      , d2.dev_tribe_effort__itops as dist_dev_tribe_effort
      , d2.dev_tribe_effort__itops_weight as dist_weight
      , round(d1.base_effort__itops * d2.dev_tribe_effort__itops_weight ,8) as distributed_effort
      --, round(d1.base_effort__itops2 * d2.dev_tribe_effort__itops_weight ,8) as distributed_effort2
      , 'Yes' as is_distributed_row
    from itops_dist_step1 d1
    inner join itops_agg d2
      on d1.period = d2.period
      --20260216 boyut eşleşmesi kaldırıldı: her proje tüm boyutlardan dağıtım alacak
    where 1=1
      and d2.yes_no = 'Yes'
  )
  --select * from itops_dist_step2
  --where project_name ='DGTRANSIT_VISA_Maintenance'  
  --select * into mart.fact_distributed_efforts_2026_new__itops from itops_dist_step2
,unions_distributed as 
(
  select * from l1_dist_step2
  union all select * from l2_dist_step2
  union all select * from app_management_dist_step2
  union all select * from infosec_dist_step2
  union all select * from itops_dist_step2
)
--select * from unions_distributed
,adjustments as (
    select
        period,
        project_id,
        project_name,
        adjustment_amount
    from {{ ref('fact_distributed_efforts_adjustment') }}
)
,finals_base as
(
  select period, project_id, project_name, customer, it_domain, category, tribe, business_line, product, managed_hosting, financial_code, is_outsource_inhouse, capex_opex, epic_id, epic_name, author_name, issue_type_name
    , base_effort_raw
    , operation_l1_support_effort
    , second_level_l2_support_effort
    , base_effort
    , team_effort_normalized
    , dev_tribe_effort, enterprise_support_effort, app_mngmt_effort, infra_system_support_effort
    , 0 as weight
    , final_effort
    , 0 as distributed_effort
    , 'No' as is_distributed_row
    , null as distribute_from
  from calc_step5
  --normalize edilmiş dağıtılan eforlar, özetlenmiş şekilde varolan eforların altına eklenir
  union all
  select
    period, project_id, project_name, customer, it_domain, category, tribe, business_line, product, managed_hosting, financial_code, is_outsource_inhouse, capex_opex, null as epic_id, 'Bakım' as epic_name, null as author_name, null as issue_type_name
    , 0 as base_effort_raw
    , 0 as operation_l1_support_effort
    , 0 as second_level_l2_support_effort
    --, dist_base_effort as base_effort
    , 0 as base_effort
    , 0 as team_effort_normalized
    , 0 as dev_tribe_effort
    --20260130 dağıtılan her bir efor ilgili metriğin altında gösterilmeli, sadece toplamda değil
    , case
        when distribute_from = 'L1' then distributed_effort
        else 0
    end as enterprise_support_effort
    , case
        when distribute_from = 'App Management' then distributed_effort
        else 0
    end as app_mngmt_effort
    , case
        when distribute_from = 'ITOPS' then distributed_effort
        else 0
    end as infra_system_support_effort
    , dist_weight as weight
    , distributed_effort as final_effort
    , distributed_effort
    --, distributed_effort2 as final_effort
    --, distributed_effort2 as distributed_effort
    , is_distributed_row
    , distribute_from
  from unions_distributed
-- IT_OPERATION (Kullanıcı Destek): User Support eforu dağıtılmaz, dönem bazında özetlenerek ham efor olarak eklenir
  union all
  select
    period
    , '-' || project_id as project_id
    , project_name
    , max(customer) as customer, max(it_domain) as it_domain
    , max(category) as category, max(tribe) as tribe
    , max(business_line) as business_line, max(product) as product
    , max(managed_hosting) as managed_hosting, max(financial_code) as financial_code
    , max(is_outsource_inhouse) as is_outsource_inhouse, max(capex_opex) as capex_opex
    , null as epic_id, null as epic_name, null as author_name, null as issue_type_name
    , sum(base_effort_raw) as base_effort_raw
    , 0 as operation_l1_support_effort
    , 0 as second_level_l2_support_effort
    , 0 as base_effort
    , 0 as team_effort_normalized
    , 0 as dev_tribe_effort, 0 as enterprise_support_effort, 0 as app_mngmt_effort, 0 as infra_system_support_effort
    , 0 as weight
    , sum(base_effort_raw) as final_effort
    , 0 as distributed_effort
    , 'No' as is_distributed_row
    , null as distribute_from
  from calc_step__4dist
  where project_name = 'IT_OPERATION (Kullanıcı Destek)'
  group by period, project_id, project_name
)
,finals as (
  -- Aggregate to project level first to match with adjustments
  select
    fb.period,
    fb.project_id,
    fb.project_name,
    fb.customer,
    fb.it_domain,
    fb.category,
    fb.tribe,
    fb.business_line,
    fb.product,
    fb.managed_hosting,
    fb.financial_code,
    fb.is_outsource_inhouse,
    fb.capex_opex,
    fb.epic_id,
    fb.epic_name,
    fb.author_name,
    fb.issue_type_name,
    fb.base_effort_raw,
    fb.operation_l1_support_effort,
    fb.second_level_l2_support_effort,
    fb.base_effort,
    fb.team_effort_normalized,
    fb.dev_tribe_effort,
    fb.enterprise_support_effort,
    fb.app_mngmt_effort,
    fb.infra_system_support_effort,
    fb.weight,
    fb.final_effort,
    fb.distributed_effort,
    fb.is_distributed_row,
    fb.distribute_from,
    -- Adjustment columns
    case
        when a.adjustment_amount is not null then true
        else false
    end as has_adjustment,
    a.adjustment_amount as manual_adjustment_amount,
    -- Adjusted metrics
    coalesce(a.adjustment_amount, fb.distributed_effort) as total_distributed_all_adjusted,
    coalesce(a.adjustment_amount, fb.final_effort) as final_effort_adjusted
  from finals_base fb
  left join adjustments a
    on fb.period = a.period
    and fb.project_id = a.project_id
)
select * from finals
  
--select distinct project_name,financial_code,customer from finals
--where financial_code is null
--and category <> 'Board'

--where isnull 
--drop table mart.fact_distributed_efforts_2026_NEW cascade;
  --select * into mart.fact_distributed_efforts_2026_new from finals
  --select * from mart.fact_distributed_efforts_2026_new where project_name ilike '%COREBANK%PTT%'  
/*
--FX ToDo : kolonların 2025 yılı için hesaplanan tablolar ile aynı olması gerekiyor
select 
    period
  --, tribe
  , project_name
  , sum(base_effort_raw) as base_effort_raw
  , sum(operation_l1_support_effort) as operation_l1_support_effort
  , sum(second_level_l2_support_effort) as second_level_l2_support_effort
  , sum(base_effort) as base_effort
  , sum(team_effort_normalized) as team_effort_normalized
  , sum(dev_tribe_effort) as dev_tribe_effort
  , sum(enterprise_support_effort) as enterprise_support_effort
  , sum(app_mngmt_effort) as app_mngmt_effort
  , sum(infra_system_support_effort) as infra_system_support_effort
  ,sum(final_effort) as final_effort
  ,sum(distributed_effort) as distributed_effort
from finals
  where 1=1
  and (tribe = 'PF' or project_name ilike 'PF_%')
group by period
  --, tribe
  , rollup(project_name)
*/
