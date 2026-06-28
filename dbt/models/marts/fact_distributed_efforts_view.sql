{{ config(
    materialized="view",
    schema="mart",
    tags=["jira", "mart", "datamart"]
) }}

with combined_efforts as 
(
    select
        "period", project_id, project_name, customer, category, it_domain, tribe, product, business_line, managed_hosting,financial_code
        , null as epic_id
        , null as epic_name
        , null as author_name
        , null as issue_type_name
        , logged_time_person_day, exclude_effort, team_effort, tribe_effort, dagitim_katsayisi, total_cus_main_effort, total_cus_main_product_effort
        , total_l1_effort, total_l2_effort, total_infosec_effort,total_l1_effort_by_issuetype,total_l2_effort_by_issuetype, project_l1_effort_by_issuetype, project_l2_effort_by_issuetype, total_hosting_firmax_effort, total_hosting_customer_effort, total_altyapi_guvenlik_effort, total_uygulama_yonetimi_effort
        , distribution_ratio_l1l2, distribution_ratio_infosec, distribution_ratio_altyapi_guvenlik_uygulama
        , distributed_team_effort, distributed_total_proje_team_efforts, distributed_l1_effort, distributed_l2_effort, distributed_infosec_effort, distributed_altyapi_guvenlik_effort, distributed_uygulama_yonetimi_effort, distributed_l1_effort_by_issuetype, distributed_l2_effort_by_issuetype
        , total_distributed_all
        , distributed_total_proje_team_efforts_debug, dist_total_proje_team_efforts
        , exclude_effort_debug
        , final_effort
        , capex_effort, opex_effort, total_effort_for_weight, capex_weight, opex_weight, final_effort_capex, final_effort_opex
        , inhouse_effort, outsource_effort, inhouse_weight, outsource_weight, final_effort_inhouse, final_effort_outsource
        , 0 as problemli_toplam, 0 as pay_per_hedef_proje
        , total_distributed_all as total_distributed_all_adjusted
        , final_effort as final_effort_adjusted
        , false as has_adjustment
        , 0 as manual_adjustment_amount
        --2026 calculation method fields
        ,0 as base_effort_raw
        ,0 as operation_l1_support_effort
        ,0 as second_level_l2_support_effort
        ,0 as base_effort
        ,0 as team_effort_normalized
        ,0 as dev_tribe_effort
        ,0 as enterprise_support_effort
        ,0 as app_mngmt_effort
        ,0 as infra_system_support_effort
        ,0 as weight
        --,0 as final_effort
        ,0 as distributed_effort
        ,null as is_distributed_row
        ,null as distribute_from
    from {{ ref('fact_distributed_efforts_2025_01_06') }}
    --tobesafe
    where period >= '2025-01' and period < '2025-07'
    union all
    select
        "period", project_id, project_name, customer, category, it_domain, tribe, product, business_line, managed_hosting,financial_code
        , null as epic_id
        , null as epic_name
        , null as author_name
        , null as issue_type_name
        , logged_time_person_day, exclude_effort, team_effort, tribe_effort, dagitim_katsayisi, total_cus_main_effort, total_cus_main_product_effort
        , total_l1_effort, total_l2_effort, total_infosec_effort,total_l1_effort_by_issuetype,total_l2_effort_by_issuetype, project_l1_effort_by_issuetype, project_l2_effort_by_issuetype, total_hosting_firmax_effort, total_hosting_customer_effort, total_altyapi_guvenlik_effort, total_uygulama_yonetimi_effort
        , distribution_ratio_l1l2, distribution_ratio_infosec, distribution_ratio_altyapi_guvenlik_uygulama
        , distributed_team_effort, distributed_total_proje_team_efforts, distributed_l1_effort, distributed_l2_effort, distributed_infosec_effort, distributed_altyapi_guvenlik_effort, distributed_uygulama_yonetimi_effort, distributed_l1_effort_by_issuetype, distributed_l2_effort_by_issuetype
        , total_distributed_all
        , distributed_total_proje_team_efforts_debug, dist_total_proje_team_efforts
        , exclude_effort_debug
        , final_effort
        , capex_effort, opex_effort, total_effort_for_weight, capex_weight, opex_weight, final_effort_capex, final_effort_opex
        , inhouse_effort, outsource_effort, inhouse_weight, outsource_weight, final_effort_inhouse, final_effort_outsource
        , problemli_toplam, pay_per_hedef_proje
        , total_distributed_all_adjusted
        , final_effort_adjusted
        , false as has_adjustment
        , 0 as manual_adjustment_amount
       --2026 calculation method fields
        ,0 as base_effort_raw
        ,0 as operation_l1_support_effort
        ,0 as second_level_l2_support_effort
        ,0 as base_effort
        ,0 as team_effort_normalized
        ,0 as dev_tribe_effort
        ,0 as enterprise_support_effort
        ,0 as app_mngmt_effort
        ,0 as infra_system_support_effort
        ,0 as weight
        --,0 as final_effort
        ,0 as distributed_effort
        ,null as is_distributed_row
        ,null as distribute_from
    from {{ ref('fact_distributed_efforts_2025_07_12') }}
    --tobesafe
    where period >= '2025-07' and period < '2026-01'
    ----2026
    union all
    select
        "period", project_id, project_name
        ,customer
        , category
        ,it_domain
        , tribe
        ,product
        ,business_line
        ,managed_hosting
        ,financial_code
        , epic_id
        , epic_name
        , author_name
        , issue_type_name
        , base_effort_raw as logged_time_person_day
        , 0 as exclude_effort, team_effort_normalized as team_effort, 0 as tribe_effort, 0 as dagitim_katsayisi, 0 as total_cus_main_effort, 0 as total_cus_main_product_effort
        , 0 as total_l1_effort, 0 as total_l2_effort, 0 as total_infosec_effort, 0 as total_l1_effort_by_issuetype, 0 as total_l2_effort_by_issuetype
        , 0 as project_l1_effort_by_issuetype, 0 as project_l2_effort_by_issuetype, 0 as total_hosting_firmax_effort, 0 as total_hosting_customer_effort, 0 as total_altyapi_guvenlik_effort, 0 as total_uygulama_yonetimi_effort
        , 0 as distribution_ratio_l1l2, 0 as distribution_ratio_infosec, 0 as distribution_ratio_altyapi_guvenlik_uygulama
        , team_effort_normalized as distributed_team_effort, dev_tribe_effort as distributed_total_proje_team_efforts
        , operation_l1_support_effort as distributed_l1_effort, second_level_l2_support_effort as distributed_l2_effort
        , enterprise_support_effort as distributed_infosec_effort
        , infra_system_support_effort as distributed_altyapi_guvenlik_effort
        , app_mngmt_effort as distributed_uygulama_yonetimi_effort
        , operation_l1_support_effort as distributed_l1_effort_by_issuetype
        , second_level_l2_support_effort as distributed_l2_effort_by_issuetype
        , distributed_effort as total_distributed_all
        , 0 as distributed_total_proje_team_efforts_debug, 0 as dist_total_proje_team_efforts
        , 0 as exclude_effort_debug
        , final_effort
        , case when capex_opex = 'Capitalized' then final_effort else 0 end as capex_effort
        , case when capex_opex = 'Expensed' then final_effort else 0 end opex_effort
        , weight as total_effort_for_weight, 0 as capex_weight, 0 as opex_weight
        , case when capex_opex = 'Capitalized' then final_effort else 0 end as final_effort_capex
        , case when capex_opex = 'Expensed' then final_effort else 0 end as final_effort_opex
        , case when is_outsource_inhouse = 'Inhouse' then final_effort else 0 end as inhouse_effort
        , case when is_outsource_inhouse = 'Outsource' then final_effort else 0 end as outsource_effort
        , 0 as inhouse_weight, 0 as outsource_weight
        , case when is_outsource_inhouse = 'Inhouse' then final_effort else 0 end as final_effort_inhouse
        , case when is_outsource_inhouse = 'Outsource' then final_effort else 0 end as final_effort_outsource
        , 0 as problemli_toplam, 0 as pay_per_hedef_proje
        , coalesce(total_distributed_all_adjusted, distributed_effort) as total_distributed_all_adjusted
        , coalesce(final_effort_adjusted, final_effort) as final_effort_adjusted
        , coalesce(has_adjustment, false) as has_adjustment
        , coalesce(manual_adjustment_amount, 0) as manual_adjustment_amount
        --FX Todo - epic_id, epic_name, dev_tribe_effort, distributed_from vs. gibi 2026 hesaplamasına özgü olan kolonlar da buraya eklenmeli
        ,base_effort_raw
        ,operation_l1_support_effort
        ,second_level_l2_support_effort
        ,base_effort
        ,team_effort_normalized
        ,dev_tribe_effort
        ,enterprise_support_effort
        ,app_mngmt_effort
        ,infra_system_support_effort
        ,weight
        --,final_effort
        ,distributed_effort
        ,is_distributed_row
        ,distribute_from
    from {{ ref('fact_distributed_efforts_2026') }}
    --tobesafe
    where period >= '2026-01' and period < '2027-01'
)
select *
from combined_efforts
where 1=1