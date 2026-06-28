{{ config(
    materialized="table",
    schema="mart",
    tags=["jira", "mart", "datamart"]
) }}


with
    base_efforts as 
    (
        select *
        from {{ ref('fact_distributed_efforts_view') }}
        where 1=1
        and period between '2026-01' and '2026-12'
    )
    ,operation_efforts as 
    (
        select
            oe.period,
            oe.project_id,
            coalesce(p.project_name, oe.project_name) as project_name,
            p.customer,
            p.category_name as category,
            p.it_domain,
            p.tribe,
            p.product,
            p.business_line,
            p.hosting as managed_hosting,
            p.financial_code,
            oe.planned_effort,
            oe.actual_effort
        from {{ ref('fact_operation_efforts') }} oe
        left join {{ ref('dim_projects_snapshot') }} p
          on oe.project_id = p.project_id
         and oe.period = p.snapshot_period
        where 1=1
        and ( nullif(oe.planned_effort,0) != 0 or nullif(oe.actual_effort,0) != 0 )
        and oe.period between '2026-01' and '2026-12'
    )
    ,final_with_operation as
    (
        select
            period, project_id, project_name, customer, category, it_domain, tribe, product, business_line, managed_hosting,financial_code,
            epic_id, epic_name,
            logged_time_person_day, exclude_effort, team_effort, tribe_effort, dagitim_katsayisi,
            total_cus_main_effort, total_cus_main_product_effort, total_l1_effort, total_l2_effort, total_infosec_effort,
            total_l1_effort_by_issuetype, total_l2_effort_by_issuetype, project_l1_effort_by_issuetype, project_l2_effort_by_issuetype,
            total_hosting_firmax_effort, total_hosting_customer_effort, total_altyapi_guvenlik_effort, total_uygulama_yonetimi_effort,
            distribution_ratio_l1l2, distribution_ratio_infosec, distribution_ratio_altyapi_guvenlik_uygulama,
            distributed_team_effort, distributed_total_proje_team_efforts, distributed_l1_effort, distributed_l2_effort,
            distributed_infosec_effort, distributed_altyapi_guvenlik_effort, distributed_uygulama_yonetimi_effort,
            total_distributed_all, distributed_total_proje_team_efforts_debug, dist_total_proje_team_efforts, exclude_effort_debug,
            final_effort, capex_effort, opex_effort,
            total_effort_for_weight, capex_weight, opex_weight, final_effort_capex, final_effort_opex,
            inhouse_effort, outsource_effort, inhouse_weight, outsource_weight, final_effort_inhouse, final_effort_outsource,
            problemli_toplam, pay_per_hedef_proje,
            total_distributed_all_adjusted, final_effort_adjusted, false as has_adjustment, 0 as manual_adjustment_amount,
            dev_tribe_effort, enterprise_support_effort, app_mngmt_effort, infra_system_support_effort as infrastructure_sysops_effort, null as infrastructure_sysops_effort_old,
            0 as total_all_with_issue_types, 0 as total_project_efforts_project_team,
            0 as operation_actual_effort,
            0 as operation_planned_effort
        from base_efforts
        --Operational Efforts
        union all
        select
            period, project_id, project_name, customer, category, it_domain, tribe, product, business_line, managed_hosting,financial_code,
            null as epic_id, null as epic_name,
            0 as logged_time_person_day, 0 as exclude_effort, 0 as team_effort, 0 as tribe_effort, 0 as dagitim_katsayisi,
            0 as total_cus_main_effort, 0 as total_cus_main_product_effort, 0 as total_l1_effort, 0 as total_l2_effort, 0 as total_infosec_effort,
            0 as total_l1_effort_by_issuetype, 0 as total_l2_effort_by_issuetype, 0 as project_l1_effort_by_issuetype,  0 as project_l2_effort_by_issuetype,
            0 as total_hosting_firmax_effort, 0 as total_hosting_customer_effort, 0 as total_altyapi_guvenlik_effort, 0 as total_uygulama_yonetimi_effort,
            0 as distribution_ratio_l1l2, 0 as distribution_ratio_infosec, 0 as distribution_ratio_altyapi_guvenlik_uygulama,
            0 as distributed_team_effort, 0 as distributed_total_proje_team_efforts, 0 as distributed_l1_effort, 0 as distributed_l2_effort,
            0 as distributed_infosec_effort, 0 as distributed_altyapi_guvenlik_effort, 0 as distributed_uygulama_yonetimi_effort,
            0 as total_distributed_all, 0 as distributed_total_proje_team_efforts_debug, 0 as dist_total_proje_team_efforts, 0 as exclude_effort_debug,
            0 as final_effort, 0 as capex_effort, 0 as opex_effort,
            0 as total_effort_for_weight, 0 as capex_weight, 0 as opex_weight, 0 as final_effort_capex, 0 as final_effort_opex,
            0 as inhouse_effort, 0 as outsource_effort, 0 as inhouse_weight, 0 as outsource_weight, 0 as final_effort_inhouse, 0 as final_effort_outsource,
            0 as problemli_toplam, 0 as pay_per_hedef_proje,
            0 as total_distributed_all_adjusted, 0 as final_effort_adjusted, false as has_adjustment, 0 as manual_adjustment_amount,
            0 as dev_tribe_effort, 0 as enterprise_support_effort, 0 as app_mngmt_effort, 0 as infrastructure_sysops_effort, 0 as infrastructure_sysops_effort_old,
            0 as total_all_with_issue_types, 0 as total_project_efforts_project_team,
            o.actual_effort as operation_actual_effort,
            o.planned_effort as operation_planned_effort
        from operation_efforts o
    )
--select * from final_with_operation
,final_recalculation as
(
    select
        period, project_id, project_name, customer, category, it_domain, tribe, product, business_line, managed_hosting,financial_code,
        epic_id, epic_name,
        logged_time_person_day, exclude_effort, team_effort, tribe_effort, dagitim_katsayisi,
        total_cus_main_effort, total_cus_main_product_effort, total_l1_effort, total_l2_effort, total_infosec_effort,
        total_l1_effort_by_issuetype, total_l2_effort_by_issuetype, project_l1_effort_by_issuetype, project_l2_effort_by_issuetype,
        total_hosting_firmax_effort, total_hosting_customer_effort, total_altyapi_guvenlik_effort, total_uygulama_yonetimi_effort,
        distribution_ratio_l1l2, distribution_ratio_infosec, distribution_ratio_altyapi_guvenlik_uygulama,
        distributed_team_effort, distributed_total_proje_team_efforts, distributed_l1_effort, distributed_l2_effort,
        distributed_infosec_effort, distributed_altyapi_guvenlik_effort, distributed_uygulama_yonetimi_effort,
        total_distributed_all, distributed_total_proje_team_efforts_debug, dist_total_proje_team_efforts, exclude_effort_debug,
        final_effort, capex_effort, opex_effort,
        total_effort_for_weight, capex_weight, opex_weight, final_effort_capex, final_effort_opex,
        inhouse_effort, outsource_effort, inhouse_weight, outsource_weight, final_effort_inhouse, final_effort_outsource,
        problemli_toplam, pay_per_hedef_proje,
        total_distributed_all_adjusted, 
        final_effort_adjusted, has_adjustment, manual_adjustment_amount,
        dev_tribe_effort, 
        enterprise_support_effort,
        app_mngmt_effort as app_management_effort,
        infrastructure_sysops_effort as infrastructure_sysops_effort_adjusted ,
        0 as total_abs_adjusted,
        --, infrastructure_sysops_effort, 
        infrastructure_sysops_effort_old,
        total_all_with_issue_types as itops_adjusted,
        -- total_project_efforts_project_team as dev_tribe_effort_adjusted,  To do ? 
        dev_tribe_effort as dev_tribe_effort_adjusted,   
        operation_actual_effort,
        operation_planned_effort 
    from final_with_operation
)
select 
    *
    ,enterprise_support_effort as enterprise_support_effort_adjusted
    ,app_management_effort as app_management_effort_adjusted
    ,infrastructure_sysops_effort_adjusted as infrastructure_sysops_effort_adj_adjusted
from final_recalculation