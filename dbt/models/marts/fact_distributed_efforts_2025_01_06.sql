{{ config(
    materialized="table",
    schema="mart",
    tags=["jira", "mart", "datamart"]
) }}

--2025-01
with
base_data_raw as (
    select
        w.snapshot_period as period,
        w.trx_date,
        w.issue_id,
        w.issue_key,
        w.worklog_id,
        w.author_name,
        w.issue_type as issue_type_name,
        w.capex_opex,
        w.is_outsource_inhouse,
        w.project_id,
        w.project_name as project_name,
        w.time_spent_seconds,
        round(w.time_spent_person_days,8) as logged_time_kg,
        coalesce(w.category_name, 'N/A') as category,
        --w.tribe,
        coalesce(w.tribe, 'Belirsiz Tribe') as tribe,
        w.customer,
        w.business_line,
        w.product,
        w.hosting as managed_hosting,
        w.financial_code,
        case
            when w.project_id = '10035' then 'Alt Yapi ve Güvenlik'     --IT OPERASYON
            when w.project_id = '10347' then 'Alt Yapi ve Güvenlik'     --IT_OPERATION
            when w.project_id = '10386' then 'L1'                       --SERVICE_DESK_L1
            when w.project_id = '10457' then 'L2'                       --HUB HEROES_SLS_L2
            when w.project_id = '10822' then 'Information Security'     --Information Security
            when w.project_id in ('10311', '10184', '10169', '10522', '10521') then 'Uygulama Yönetimi'     --SHADOW DEVOPS,SHADOW TALEP HAVUZU,SHADOW TEAM,Hub Heroes - Devops,Hub Heroes - Uygulama Yönetimi
            when w.project_name ilike '%TEAM%' then 'Board'
            else 'Diğer'
        end as total_itops_efforts,
        case
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
            else 0.0000
        end as exclude_effort
    from {{ ref('fact_worklogs_snapshot') }}  w
    where 1 = 1
        and w.trx_date >= '2025-01-01' and w.trx_date < '2025-07-01'
        and w.is_period_locked = true
        ----debug
        -- and w.snapshot_period = '2025-06'
        -- and w.project_name LIKE '%ACQUIRING_NEOPAY%'   
)
,base_data as (
    select
        period,
        trx_date,
        issue_id,
        issue_key,
        worklog_id,
        author_name,
        issue_type_name,
        capex_opex,
        is_outsource_inhouse,
        project_id,
        project_name,
        time_spent_seconds,
        logged_time_kg,
        category,
        tribe,
        customer,
        business_line,
        product,
        managed_hosting,
        financial_code,
        total_itops_efforts,
        exclude_effort
    from base_data_raw
    where not (project_name = 'IT_OPERATION' and issue_type_name != 'User Support')
    union all
    select
        period,
        trx_date,
        issue_id,
        issue_key,
        worklog_id,
        author_name,
        issue_type_name,
        capex_opex,
        'Inhouse' as is_outsource_inhouse,
        '-' || project_id as project_id,
        'IT_OPERATION (Without)' as project_name,   --ITOPS Without user support.
        time_spent_seconds,
        logged_time_kg,
        'N/A' as category,
        tribe,
        customer,
        business_line,
        product,
        managed_hosting,
        financial_code,
        total_itops_efforts,
        exclude_effort
    from base_data_raw
    where project_name = 'IT_OPERATION'
      and issue_type_name != 'User Support'  
)
-- select * from base_data     
,tribe_efforts as 
(
    select
        period,
        coalesce(tribe, 'Belirsiz Tribe') as tribe,
        sum(
            case 
                when category = 'Board' 
                then logged_time_kg 
                else 0 
            end
        ) as board_effort,
        sum(
            case
                when coalesce(category, '') != 'Board'
                then logged_time_kg
                else 0
            end
        ) as non_board_effort
    from base_data_raw
    group by period
        ,coalesce(tribe, 'Belirsiz Tribe')
)
--select * from tribe_efforts
,total_cus_main_effort as 
(
    select period
        , sum(logged_time_kg) as total_cus_main_effort
    from base_data_raw
    where category in ('Maintenance & CRs', 'Customer')
    group by period
)
--select * from total_cus_main_effort
,total_cus_main_product_effort as 
(
    select period
        , sum(logged_time_kg) as total_cus_main_product_effort
    from base_data_raw
    where category in ('Maintenance & CRs', 'Customer', 'Product')
    group by period
)
,total_l1_effort as 
(
    select period
        , sum(logged_time_kg) as total_l1_effort
    from base_data_raw
    where total_itops_efforts = 'L1'
    group by period
)
,total_l2_effort as 
(
    select period
        , sum(logged_time_kg) as total_l2_effort
    from base_data_raw
    where total_itops_efforts = 'L2'
    group by period
)
,total_is_effort as 
(
    select period
        , sum(logged_time_kg) as total_is_effort
    from base_data_raw
    where total_itops_efforts = 'Information Security'
    group by period
)
,total_hosting_firmax_effort as 
(
    select period
        , sum(logged_time_kg) as total_hosting_firmax_effort
    from base_data_raw
    where managed_hosting = 'HostingFirmaX'
    group by period
)
,total_hosting_customer_effort as 
(
    select period
        , sum(logged_time_kg) as total_hosting_customer_effort
    from base_data_raw
    where managed_hosting = 'HostingCustomer'
    group by period
)
,total_altyapi_guvenlik_effort as 
(
    select period
        , sum(logged_time_kg) as total_altyapi_guvenlik_effort
    from base_data_raw
    where total_itops_efforts = 'Alt Yapi ve Güvenlik'
    and issue_type_name != 'User Support'
    group by period
)
,total_uygulama_yonetimi_effort as 
(
    select period
        , sum(logged_time_kg) as total_uygulama_yonetimi_effort
    from base_data_raw
    where total_itops_efforts = 'Uygulama Yönetimi'
    group by period

),total_l1_effort_by_issuetype as 
(
    select period
        , sum(logged_time_kg) as total_l1_effort_by_issuetype
    from base_data_raw
    where issue_type_name = 'Operation & L1 Support'
    group by period
)
,total_l2_effort_by_issuetype as 
(
    select period
        , sum(logged_time_kg) as total_l2_effort_by_issuetype
    from base_data_raw
    where issue_type_name = 'Second Level Support (L2)'
    group by period
)
,distrubition_base_1 as 
(
    select
        bd.period,
        bd.project_id,
        bd.project_name,
        bd.customer,
        bd.category,
        bd.total_itops_efforts as "it_domain",
        bd.tribe,
        bd.product,
        bd.business_line,
        bd.managed_hosting,
        bd.financial_code,
        sum(bd.logged_time_kg) as logged_time_person_day,
        sum(bd.exclude_effort) as exclude_effort,
        max(te.board_effort) as team_effort,
        max(te.non_board_effort) as tribe_effort,
        round(sum(bd.logged_time_kg) / nullif(max(te.non_board_effort), 0),8) as dagitim_katsayisi,  -- toplam_efor(person_day) / tribe_effort
        coalesce(max(tce.total_cus_main_effort) ,0) as total_cus_main_effort,
        coalesce(max(tcpe.total_cus_main_product_effort) ,0) as total_cus_main_product_effort,
        coalesce(max(tl1.total_l1_effort) ,0) as total_l1_effort,
        coalesce(max(tl2.total_l2_effort) ,0) as total_l2_effort,
        coalesce(max(tis.total_is_effort) ,0) as total_infosec_effort,
        coalesce(max(tl1is.total_l1_effort_by_issuetype),0) as total_l1_effort_by_issuetype,
        coalesce(max(tl2is.total_l2_effort_by_issuetype),0) as total_l2_effort_by_issuetype,
        --Proje bazında L1/L2 Issue Type eforları
        round(sum(case when bd.issue_type_name = 'Operation & L1 Support' then bd.logged_time_kg else 0 end), 8) as project_l1_effort_by_issuetype,
        round(sum(case when bd.issue_type_name = 'Second Level Support (L2)' then bd.logged_time_kg else 0 end), 8) as project_l2_effort_by_issuetype,
        coalesce(max(thd.total_hosting_firmax_effort) ,0) as total_hosting_firmax_effort,
        coalesce(max(thc.total_hosting_customer_effort) ,0) as total_hosting_customer_effort,
        coalesce(max(tagy.total_altyapi_guvenlik_effort) ,0) as total_altyapi_guvenlik_effort,
        coalesce(max(tuy.total_uygulama_yonetimi_effort) ,0) as total_uygulama_yonetimi_effort,
        round(
        case
            when bd.category in ('Customer', 'Maintenance & CRs')
            then
                sum(bd.logged_time_kg) --logged_time_person_day
                /
                nullif(max(tce.total_cus_main_effort), 0) --total_cus_main_effort
            else 0
        end,8) as distribution_ratio_l1l2,
        round(
        case
            when bd.category in ('Customer', 'Maintenance & CRs', 'Product')
            then
                sum(bd.logged_time_kg)
                /
                nullif(max(tcpe.total_cus_main_product_effort), 0)
            else 0
        end,8) as distribution_ratio_infosec,
        round(
        case
            when bd.managed_hosting = 'HostingFirmaX'
            then
                sum(bd.logged_time_kg)
                /
                nullif(max(thd.total_hosting_firmax_effort), 0)
            else 0
        end,8) as distribution_ratio_altyapi_guvenlik_uygulama
    from base_data bd
    left join tribe_efforts te
        on bd.period = te.period
        and coalesce(bd.tribe, 'Belirsiz Tribe') = te.tribe
    left join total_cus_main_effort tce on bd.period = tce.period
    left join total_cus_main_product_effort tcpe on bd.period = tcpe.period
    left join total_l1_effort tl1 on bd.period = tl1.period
    left join total_l2_effort tl2 on bd.period = tl2.period
    left join total_is_effort tis on bd.period = tis.period
    left join total_l1_effort_by_issuetype tl1is on bd.period= tl1is.period
    left join total_l2_effort_by_issuetype tl2is on bd.period= tl2is.period
    left join total_hosting_firmax_effort thd on bd.period = thd.period
    left join total_hosting_customer_effort thc on bd.period = thc.period
    left join total_altyapi_guvenlik_effort tagy on bd.period = tagy.period
    left join total_uygulama_yonetimi_effort tuy on bd.period = tuy.period
    group by
        bd.period,
        bd.project_id,
        bd.project_name,
        bd.customer,
        bd.category,
        bd.total_itops_efforts,
        bd.tribe,
        bd.product,
        bd.business_line,
        bd.managed_hosting,
        bd.financial_code
)
-- select * from distrubition_base_1
,distrubition_base_2 as 
(
    select
        *,
        round(team_effort * dagitim_katsayisi ,8) as distributed_team_effort,
        round(logged_time_person_day + (team_effort * dagitim_katsayisi) ,8) as distributed_total_proje_team_efforts
    from distrubition_base_1
)
-- select * from distrubition_base_2
,distributed_efforts as
(
    select
        *,
        round(dist.total_l1_effort * dist.distribution_ratio_l1l2 ,8) as distributed_l1_effort,
        round(dist.total_l2_effort * dist.distribution_ratio_l1l2 ,8) as distributed_l2_effort,
        round(dist.total_infosec_effort * dist.distribution_ratio_infosec ,8) as distributed_infosec_effort,
        round(dist.total_altyapi_guvenlik_effort * dist.distribution_ratio_altyapi_guvenlik_uygulama ,8) as distributed_altyapi_guvenlik_effort,
        round(dist.total_uygulama_yonetimi_effort * dist.distribution_ratio_altyapi_guvenlik_uygulama ,8) as distributed_uygulama_yonetimi_effort,
        --L1/L2 Issue Type dağıtımları (sadece gösterim amaçlı, toplama dahil değil)
        round(dist.total_l1_effort_by_issuetype * dist.distribution_ratio_l1l2 ,8) as distributed_l1_effort_by_issuetype,
        round(dist.total_l2_effort_by_issuetype * dist.distribution_ratio_l1l2 ,8) as distributed_l2_effort_by_issuetype
    from distrubition_base_2 as dist
)
-- select * from distributed_efforts
,capex_opex_weights as 
(
    select
        period,
        project_id,
        project_name,
        -- Calculate total effort by capex_opex type at project/period level
        sum(case when lower(capex_opex) = 'capitalized' then logged_time_kg else 0 end) as capex_effort,
        sum(case when lower(capex_opex) = 'expensed' then logged_time_kg else 0 end) as opex_effort,
        sum(logged_time_kg) as total_effort_for_weight,
        -- Calculate weight ratios
        round(
            sum(case when lower(capex_opex) = 'capitalized' then logged_time_kg else 0 end)
            / nullif(sum(logged_time_kg), 0)
            ,8
        ) as capex_weight,
        round(
            sum(case when lower(capex_opex) = 'expensed' then logged_time_kg else 0 end)
            / nullif(sum(logged_time_kg), 0)
            ,8
        ) as opex_weight
    from base_data
    group by period, project_id, project_name
)
,inhouse_outsource_weights as 
(
    select
        period,
        project_id,
        project_name,
        -- Calculate total effort by capex_opex type at project/period level
        sum(case when lower(is_outsource_inhouse) = 'inhouse' then logged_time_kg else 0 end) as inhouse_effort,
        sum(case when lower(is_outsource_inhouse) = 'outsource' then logged_time_kg else 0 end) as outsource_effort,
        sum(logged_time_kg) as total_effort_for_weight,
        -- Calculate weight ratios
        round(
            sum(case when lower(is_outsource_inhouse) = 'inhouse' then logged_time_kg else 0 end)
            / nullif(sum(logged_time_kg), 0)
            ,8
        ) as inhouse_weight,
        round(
            sum(case when lower(is_outsource_inhouse) = 'outsource' then logged_time_kg else 0 end)
            / nullif(sum(logged_time_kg), 0)
            ,8
        ) as outsource_weight
    from base_data
    group by period, project_id, project_name
)
-- select * from capex_opex_weights
,final as
(
    select
        de.*,
        (de.distributed_l1_effort
        + de.distributed_l2_effort
        + de.distributed_infosec_effort
        + de.distributed_altyapi_guvenlik_effort
        + de.distributed_uygulama_yonetimi_effort) as total_distributed_all,
        de.distributed_total_proje_team_efforts as distributed_total_proje_team_efforts_debug,
        de.distributed_total_proje_team_efforts
        + (
            de.distributed_l1_effort
            + de.distributed_l2_effort
            + de.distributed_infosec_effort
            + de.distributed_altyapi_guvenlik_effort
            + de.distributed_uygulama_yonetimi_effort
        ) as dist_total_proje_team_efforts,
        de.exclude_effort as exclude_effort_debug,
        de.distributed_total_proje_team_efforts
        + (
            de.distributed_l1_effort
            + de.distributed_l2_effort
            + de.distributed_infosec_effort
            + de.distributed_altyapi_guvenlik_effort
            + de.distributed_uygulama_yonetimi_effort
        )
        - de.exclude_effort as final_effort,
        -- CAPEX/OPEX weights and calculations
        cow.capex_effort,
        cow.opex_effort,
        cow.total_effort_for_weight,
        coalesce(cow.capex_weight, 0) as capex_weight,
        coalesce(cow.opex_weight, 0) as opex_weight,
        round(
            (de.distributed_total_proje_team_efforts
            + (
                de.distributed_l1_effort
                + de.distributed_l2_effort
                + de.distributed_infosec_effort
                + de.distributed_altyapi_guvenlik_effort
                + de.distributed_uygulama_yonetimi_effort
            )
            - de.exclude_effort) * coalesce(cow.capex_weight, 0)
            ,8
        ) as final_effort_capex,
        round(
            (de.distributed_total_proje_team_efforts
            + (
                de.distributed_l1_effort
                + de.distributed_l2_effort
                + de.distributed_infosec_effort
                + de.distributed_altyapi_guvenlik_effort
                + de.distributed_uygulama_yonetimi_effort
            )
            - de.exclude_effort) * coalesce(cow.opex_weight, 0)
            ,8
        ) as final_effort_opex
    from distributed_efforts de
    left join capex_opex_weights cow
        on de.period = cow.period
        and de.project_id = cow.project_id  
    where 1 = 1
    and coalesce(de.category, 'N/A') not in ('Board')
)
,final_1 as
(
    select 
        de.*,
        iow.inhouse_effort,
        iow.outsource_effort,
        coalesce(iow.inhouse_weight, 0) as inhouse_weight,
        coalesce(iow.outsource_weight, 0) as outsource_weight,
        -- Yeni hesaplama: Inhouse = Final Effort - Outsource (ham efor)
        de.final_effort - coalesce(iow.outsource_effort, 0) as final_effort_inhouse,
        -- Outsource = Ham outsource eforu (dağıtılmamış)
        coalesce(iow.outsource_effort, 0) as final_effort_outsource
    from final de
    left join inhouse_outsource_weights iow
            on de.period = iow.period
            and de.project_id = iow.project_id
)
select *
    ,current_timestamp as _etl_date
from final_1
where 1=1
----debug
-- and tribe = 'Card Payment Systems'
-- and bd.category = 'Product'