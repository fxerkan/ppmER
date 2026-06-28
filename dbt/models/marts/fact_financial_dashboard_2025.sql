{{ config(
    materialized="table",
    schema="mart",
    tags=["jira", "mart", "datamart"]
) }}

{#
  2025 Financial Dashboard dataset Enhanced with Manual Adjustments

  Logic:
  - If adjustment_amount is NOT NULL and != 0: use adjustment_amount
  - Otherwise: use the original final_effort_adjusted from distributed efforts
#}


with
    base_efforts as 
    (
        select *
        from {{ ref('fact_distributed_efforts_view') }}
        where 1=1
        and period between '2025-01' and '2025-12'
    )
    ,adjustments as 
    (
        select
            period,
            project_id,
            project_name,
            adjustment_amount
        from {{ ref('fact_distributed_efforts_adjustment') }}
    )
    ,capex_opex_adjustment as 
    (
        select
            period,
            project_id,
            project_name,
            ratio_capex,
            ratio_opex
        from {{ ref('fact_capex_opex_adjustment') }}
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
        and oe.period between '2025-01' and '2025-12'
    )
    ,final as
    (
        select
            e.period,
            e.project_id,
            e.project_name,
            e.customer,
            e.category,
            e.it_domain,
            e.tribe,
            e.product,
            e.business_line,
            e.managed_hosting,
            e.financial_code,
            e.epic_id,
            e.epic_name,
            e.logged_time_person_day,
            e.exclude_effort,
            e.team_effort,
            e.tribe_effort,
            e.dagitim_katsayisi,
            e.total_cus_main_effort,
            e.total_cus_main_product_effort,
            e.total_l1_effort,
            e.total_l2_effort,
            e.total_infosec_effort,
            e.total_l1_effort_by_issuetype,
            e.total_l2_effort_by_issuetype,
            e.project_l1_effort_by_issuetype,
            e.project_l2_effort_by_issuetype,
            e.total_hosting_firmax_effort,
            e.total_hosting_customer_effort,
            e.total_altyapi_guvenlik_effort,
            e.total_uygulama_yonetimi_effort,
            e.distribution_ratio_l1l2,
            e.distribution_ratio_infosec,
            e.distribution_ratio_altyapi_guvenlik_uygulama,
            e.distributed_team_effort,
            e.distributed_total_proje_team_efforts,
            e.distributed_l1_effort,
            e.distributed_l2_effort,
            e.distributed_infosec_effort,
            e.distributed_altyapi_guvenlik_effort,
            e.distributed_uygulama_yonetimi_effort,
            e.total_distributed_all,
            e.distributed_total_proje_team_efforts_debug,
            e.dist_total_proje_team_efforts,
            e.exclude_effort_debug,
            e.final_effort,
            coalesce(a.adjustment_amount, e.final_effort) * c.ratio_capex as capex_effort,
            coalesce(a.adjustment_amount, e.final_effort) - (coalesce(a.adjustment_amount, e.final_effort) * c.ratio_capex) as opex_effort,
            e.total_effort_for_weight,
            c.ratio_capex as capex_weight,
            c.ratio_opex as opex_weight,
            e.final_effort_capex,
            e.final_effort_opex,
            e.inhouse_effort,
            e.outsource_effort,
            e.inhouse_weight,
            e.outsource_weight,
            e.final_effort_inhouse,
            e.final_effort_outsource,
            e.problemli_toplam,
            e.pay_per_hedef_proje,
            e.total_distributed_all_adjusted,
            -- Apply adjustment logic: if adjustment exists, use it; otherwise use original
            coalesce(a.adjustment_amount, e.final_effort) as final_effort_adjusted,
            case
                when a.adjustment_amount is not null then true
                else false
            end as has_adjustment,
            a.adjustment_amount as manual_adjustment_amount,
            -- New Calculated Metrics
            -- Infrs & SysOps Effort (new calculation - might be negative)
            (coalesce(a.adjustment_amount, e.final_effort)
             - (e.logged_time_person_day - e.project_l1_effort_by_issuetype - e.project_l2_effort_by_issuetype + e.distributed_team_effort)
             - (e.distributed_l1_effort + e.project_l1_effort_by_issuetype)
             - (e.distributed_uygulama_yonetimi_effort + e.project_l2_effort_by_issuetype)) as infrastructure_sysops_effort_new,
            -- Infrs & SysOps Effort (old calculation)
            (e.total_distributed_all_adjusted
             - e.distributed_l1_effort
             - e.distributed_uygulama_yonetimi_effort
             - e.distributed_l2_effort) as infrastructure_sysops_effort_old,
            -- Infrs & SysOps Effort = if new is negative, use old
            case
                when (coalesce(a.adjustment_amount, e.final_effort)
                     - (e.logged_time_person_day - e.project_l1_effort_by_issuetype - e.project_l2_effort_by_issuetype + e.distributed_team_effort)
                     - (e.distributed_l1_effort + e.project_l1_effort_by_issuetype)
                     - (e.distributed_uygulama_yonetimi_effort + e.project_l2_effort_by_issuetype)) < 0
                then (e.total_distributed_all_adjusted - e.distributed_l1_effort - e.distributed_uygulama_yonetimi_effort - e.distributed_l2_effort)
                else (coalesce(a.adjustment_amount, e.final_effort)
                     - (e.logged_time_person_day - e.project_l1_effort_by_issuetype - e.project_l2_effort_by_issuetype + e.distributed_team_effort)
                     - (e.distributed_l1_effort + e.project_l1_effort_by_issuetype)
                     - (e.distributed_uygulama_yonetimi_effort + e.project_l2_effort_by_issuetype))
            end as infrastructure_sysops_effort,
            -- Dev. Tribe Effort = logged_time_person_day - L1_Issue_Type - L2_Issue_Type + distributed_team_effort
            -- If infrastructure_sysops_effort_new is negative: dev_tribe - infra_old + infra_new (hem old hem negatif değeri çıkart)
            case
                when (coalesce(a.adjustment_amount, e.final_effort)
                     - (e.logged_time_person_day - e.project_l1_effort_by_issuetype - e.project_l2_effort_by_issuetype + e.distributed_team_effort)
                     - (e.distributed_l1_effort + e.project_l1_effort_by_issuetype)
                     - (e.distributed_uygulama_yonetimi_effort + e.project_l2_effort_by_issuetype)) < 0
                then (e.logged_time_person_day - e.project_l1_effort_by_issuetype - e.project_l2_effort_by_issuetype + e.distributed_team_effort)
                     - (e.total_distributed_all_adjusted - e.distributed_l1_effort - e.distributed_uygulama_yonetimi_effort - e.distributed_l2_effort)
                     + (coalesce(a.adjustment_amount, e.final_effort)
                        - (e.logged_time_person_day - e.project_l1_effort_by_issuetype - e.project_l2_effort_by_issuetype + e.distributed_team_effort)
                        - (e.distributed_l1_effort + e.project_l1_effort_by_issuetype)
                        - (e.distributed_uygulama_yonetimi_effort + e.project_l2_effort_by_issuetype))
                else (e.logged_time_person_day - e.project_l1_effort_by_issuetype - e.project_l2_effort_by_issuetype + e.distributed_team_effort)
            end as dev_tribe_effort,
            -- Ente. Sup. Effort = distributed_l1_effort + L1_Issue_Type
            (e.distributed_l1_effort + e.project_l1_effort_by_issuetype) as enterprise_support_effort,
            -- App. Man. Effort = distributed_uygulama_yonetimi_effort + L2_Issue_Type
            (e.distributed_uygulama_yonetimi_effort + e.project_l2_effort_by_issuetype) as app_management_effort,
            -- Total L1+L2+Alt Yapi ve Güvenlik+Uygulama Yönetimi+IS_Efforts (Sarı alan (Prob ekli))
            -- = total_distributed_all_adjusted + L1_Issue_Type + L2_Issue_Type
            (e.total_distributed_all_adjusted + e.project_l1_effort_by_issuetype + e.project_l2_effort_by_issuetype) as total_all_with_issue_types,
            -- Total_Project_Efforts(Project_Team) = final_effort_adjusted - total_all_with_issue_types (Mavi alan)
            (coalesce(a.adjustment_amount, e.final_effort)
             - (e.total_distributed_all_adjusted + e.project_l1_effort_by_issuetype + e.project_l2_effort_by_issuetype)) as total_project_efforts_project_team
        from base_efforts e
        left join adjustments a
            on e.period = a.period
            and e.project_id = a.project_id
        left join capex_opex_adjustment c
            on e.period = c.period
            and e.project_id = c.project_id    
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
            total_distributed_all_adjusted, final_effort_adjusted, has_adjustment, manual_adjustment_amount,
            dev_tribe_effort, enterprise_support_effort, app_management_effort, infrastructure_sysops_effort, infrastructure_sysops_effort_old,
            total_all_with_issue_types, total_project_efforts_project_team,
            0 as operation_actual_effort,
            0 as operation_planned_effort
        from final
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
            0 as dev_tribe_effort, 0 as enterprise_support_effort, 0 as app_management_effort, 0 as infrastructure_sysops_effort, 0 as infrastructure_sysops_effort_old,
            0 as total_all_with_issue_types, 0 as total_project_efforts_project_team,
            o.actual_effort as operation_actual_effort,
            o.planned_effort as operation_planned_effort
        from operation_efforts o
    )
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
        total_distributed_all_adjusted, final_effort_adjusted, has_adjustment, manual_adjustment_amount,
        dev_tribe_effort, 
        enterprise_support_effort,
        app_management_effort,
        total_all_with_issue_types-enterprise_support_effort-app_management_effort as infrastructure_sysops_effort_adjusted,
        enterprise_support_effort+app_management_effort+ABS(total_all_with_issue_types-enterprise_support_effort-app_management_effort) as total_abs_adjusted,
        --, infrastructure_sysops_effort, 
        infrastructure_sysops_effort_old,
        total_all_with_issue_types as itops_adjusted,
        total_project_efforts_project_team as dev_tribe_effort_adjusted,
        operation_actual_effort,
        operation_planned_effort 
    from final_with_operation
)
select
    *
    ,case
        when infrastructure_sysops_effort_old < 0
        then ROUND(coalesce(enterprise_support_effort / nullif(total_abs_adjusted,0) * itops_adjusted,0)::numeric,8)
        else enterprise_support_effort
    end as enterprise_support_effort_adjusted
    --,ROUND(coalesce(enterprise_support_effort / nullif(total_abs_adjusted,0) * itops_adjusted,0)::numeric,8) as enterprise_support_effort_adjusted
     ,case
        when infrastructure_sysops_effort_old < 0
        then ROUND(coalesce(app_management_effort / nullif(total_abs_adjusted,0) * itops_adjusted,0)::numeric,8)
        else app_management_effort
    end as app_management_effort_adjusted
    ,case
        when infrastructure_sysops_effort_old < 0
        then ROUND(coalesce(ABS(infrastructure_sysops_effort_adjusted) / nullif(total_abs_adjusted,0) * itops_adjusted,0)::numeric,8)
        else infrastructure_sysops_effort_adjusted
    end as infrastructure_sysops_effort_adj_adjusted
from final_recalculation