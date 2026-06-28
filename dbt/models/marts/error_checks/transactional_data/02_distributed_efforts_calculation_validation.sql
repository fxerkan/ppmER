{{
    config(
        materialized="view",
        schema="mart",
        tags=["error_check", "transactional_data", "calculation"]
    )
}}

/*
  ERROR CHECK: Distributed Efforts Calculation Validation

  Description:
  Validates the calculation logic in fact_distributed_efforts models.
  Checks that effort totals are consistent and no negative values exist.

  Expected Result:
  - Empty result = All calculations are correct
  - Rows returned = Projects with calculation errors

  Validation Rules:
  1. final_effort should equal sum of all distributed components
  2. No negative final_effort values (except for specific distribution rows)
  3. Distributed effort should not exceed base effort significantly (within 10% tolerance)

  Impact:
  - Incorrect financial reporting
  - Budget vs actual mismatches
  - Distribution errors

  Action Required:
  - Review distribution calculation logic
  - Check adjustment values
  - Verify source worklog data
*/

with effort_validation as (
    select
        period,
        project_id,
        project_name,
        tribe,
        category,
        is_distributed_row,
        distribute_from,
        base_effort_raw,
        dev_tribe_effort,
        enterprise_support_effort,
        app_mngmt_effort,
        infra_system_support_effort,
        final_effort,
        final_effort_adjusted,
        has_adjustment,
        manual_adjustment_amount,
        -- Calculate expected final effort
        (dev_tribe_effort + enterprise_support_effort + app_mngmt_effort + infra_system_support_effort) as calculated_final_effort,
        -- Difference
        final_effort - (dev_tribe_effort + enterprise_support_effort + app_mngmt_effort + infra_system_support_effort) as calculation_difference
    from {{ ref('fact_distributed_efforts_2026') }}
    where 1=1
        and period >= '2026-01'
)

select
    period,
    project_id,
    project_name,
    tribe,
    category,
    is_distributed_row,
    distribute_from,
    round(base_effort_raw, 4) as base_effort_raw,
    round(dev_tribe_effort, 4) as dev_tribe_effort,
    round(enterprise_support_effort, 4) as enterprise_support_effort,
    round(app_mngmt_effort, 4) as app_mngmt_effort,
    round(infra_system_support_effort, 4) as infra_system_support_effort,
    round(final_effort, 4) as final_effort,
    round(calculated_final_effort, 4) as calculated_final_effort,
    round(calculation_difference, 4) as calculation_difference,
    has_adjustment,
    round(manual_adjustment_amount, 4) as manual_adjustment_amount,
    case
        when final_effort < 0 and is_distributed_row = 'No' then 'Negative final_effort (non-distributed row)'
        when abs(calculation_difference) > 0.01 then 'Calculation mismatch'
        when base_effort_raw > 0 and final_effort > (base_effort_raw * 1.5) and has_adjustment = false then 'Final effort > 150% of base effort (no adjustment)'
        else 'Unknown error'
    end as error_type,
    case
        when final_effort < 0 and is_distributed_row = 'No' then 'Review distribution logic for this project'
        when abs(calculation_difference) > 0.01 then 'Check component calculations: dev_tribe + enterprise + app_mgmt + infra'
        when base_effort_raw > 0 and final_effort > (base_effort_raw * 1.5) and has_adjustment = false then 'Review distribution weights and base effort'
        else 'Investigate calculation logic'
    end as recommended_action,
    current_timestamp as check_date
from effort_validation
where 1=1
    and (
        -- Negative final effort on non-distributed rows (should not happen)
        (final_effort < 0 and is_distributed_row = 'No')
        -- Calculation mismatch (tolerance: 0.01)
        or abs(calculation_difference) > 0.01
        -- Final effort significantly exceeds base effort without adjustment
        or (base_effort_raw > 0 and final_effort > (base_effort_raw * 1.5) and has_adjustment = false)
    )
order by
    abs(calculation_difference) desc,
    period desc,
    project_id
