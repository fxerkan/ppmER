# PPM Data Stack — Business Glossary & Data Dictionary

## Overview

This document describes the PPM (Project & Portfolio Management) data warehouse built on Jira data.
The warehouse follows a 3-layer architecture: **staging → core → mart**.

## Domain Glossary

| Term | Definition |
|------|-----------|
| **Project** | A Jira project representing a software delivery initiative |
| **Issue** | A Jira ticket (Epic, Story, Task, Bug, Sub-task) |
| **Epic** | A large body of work with multiple stories/tasks |
| **Worklog / Effort** | Time logged by a user against a Jira issue (in seconds) |
| **Story Points** | Relative size estimation unit for issues |
| **Sprint** | Time-boxed iteration (usually 2 weeks) |
| **PPM** | Project & Portfolio Management — tracking multiple projects across the organization |
| **Missing Effort** | Issues that are In-Progress or Done but have no time logged |
| **Progress %** | closed_issues / total_issues * 100 |
| **Health Score** | Composite score based on completion rate, overdue issues, effort logged |
| **Lead** | Project/team lead in Jira |
| **Reporter** | Person who created the issue |
| **Assignee** | Person responsible for the issue |
| **DLT** | Data Load Tool — the ingestion framework used to pull Jira data |

---

## Schema Architecture

```
Jira API
  └── dlt ingestion → raw_jira schema (raw tables)
        └── dbt staging → staging schema (cleaned views)
              └── dbt core → core schema (dim_* and fact_* tables)
                    └── dbt marts → mart schema (business-ready aggregations)
```

---

## `core.dim_hr`
HR dimension table for human resources information. Pure HR data providing organizational hierarchy, employment status, and team structure without Jira user mapping. Use this table for: - HR reporting and analytics - Organizational structure analysis - Employee roster management - Team composition analysis

| Column | Description |
|--------|-------------|
| `user_account_id` | Primary key - Unique user account ID |
| `user_name` | User's name |
| `user_display_name` | User's display name |
| `unit_name` | Organizational unit name |
| `team_name` | Team name |
| `manager_name` | Manager's name |
| `deputy_gm_name` | Deputy General Manager's name |
| `deputy_gm_upper_unit` | Deputy GM's upper organizational unit |
| `is_active` | Employment active status |
| `is_manages_team` | Whether user manages a team |
| `is_outsource_inhouse` | Employment type (outsource/inhouse) |
| `employment_start_date` | Employment start date |
| `company_info` | Company information |
| `issue_id` | Related Jira issue ID (if applicable) |
| `issue_key` | Related Jira issue key (if applicable) |
| `created_date` | Record creation date |
| `_dlt_load_id` | DLT load ID for lineage tracking |
| `_dlt_id` | DLT record ID |
| `_etl_date` | ETL processing timestamp |

## `core.dim_users`
User dimension table with HR enrichment and productivity metrics. Combines Jira users with HR data to create a comprehensive user dimension including organizational hierarchy, employment details, and basic productivity metrics. Use this table for: - User profile lookups - Team and organizational analysis - User productivity dashboards - Workload balancing

| Column | Description |
|--------|-------------|
| `user_id` | Primary key - Unique user account ID |
| `display_name` | User's display name from Jira |
| `email` | User's email address |
| `full_name` | Full name from HR data or display_name |
| `is_active` | Combined active status from Jira and HR |
| `unit` | Organizational unit from HR |
| `team` | Team name from HR |
| `total_assigned_issues` | Total issues currently assigned to user |
| `completed_issues` | Number of completed issues |
| `completion_rate_pct` | Percentage of assigned issues completed |
| `total_hours_logged` | Total hours logged in worklogs |

## `core.dim_projects`
Project dimension table with portfolio properties and metrics. Combines Jira projects with portfolio properties and aggregated metrics to create a comprehensive project dimension for analytics. Use this table for: - Project portfolio management - Business line analysis - Project performance tracking

| Column | Description |
|--------|-------------|
| `project_id` | Primary key - Unique project identifier |
| `project_key` | Project key (e.g., SD, DEV) |
| `project_name` | Project name |
| `business_line` | Portfolio property - Business Line |
| `customer` | Portfolio property - Customer |
| `product` | Portfolio property - Product |
| `tribe` | Portfolio property - Tribe |
| `total_issues` | Total issues in the project |
| `completion_pct` | Issue completion percentage |
| `total_hours_logged` | Total hours logged in worklogs |

## `core.dim_issues`
Issue dimension table with relationship and time metrics. Comprehensive issue dimension with relationship metrics, subtask progress, and time-based calculations. Use this table for: - Issue detail lookups - Relationship network analysis - Issue aging analysis

| Column | Description |
|--------|-------------|
| `issue_id` | Primary key - Unique issue identifier |
| `issue_key` | Issue key (e.g., SD-1234) |
| `issue_summary` | Issue title/summary |
| `issue_type` | Type of issue |
| `status_category` | Status category (To Do, In Progress, Done) |
| `project_id` | Foreign key to dim_projects |
| `project_key` | Project key |
| `assignee_id` | Foreign key to dim_users (assignee) |
| `reporter_id` | Foreign key to dim_users (reporter) |
| `total_issue_links` | Total number of issue links |
| `total_subtasks` | Total number of subtasks |
| `age_days` | Days since issue creation |
| `is_overdue` | Whether issue is past due date |

## `core.dim_calendar`
Calendar Date dimension table for date-based analysis. Reference table providing date attributes, period calculations, and closure flags for snapshot management. Use this table for: - Date-based joins and analysis - Period closure determination - Fiscal period calculations

| Column | Description |
|--------|-------------|
| `calendar_date` | Full date value |
| `date_key` | YYYYMMDD format |
| `year_month` | Year-month string (YYYY-MM) |
| `is_month_closed` | Whether the month is closed (before current month) |
| `is_quarter_closed` | Whether the quarter is closed |
| `is_year_closed` | Whether the year is closed |

## `core.fact_issues`
Issue fact table (incremental) with denormalized context. Stores issues as facts with project context, relationship metrics, and time calculations for efficient querying. Use this table for: - Issue-level reporting - Project portfolio analysis - Trend analysis over time

| Column | Description |
|--------|-------------|
| `issue_id` | Primary key - Unique issue identifier |
| `issue_key` | Issue key (e.g., SD-1234) |
| `project_key` | Foreign key to dim_projects |
| `business_line` | Denormalized business line |
| `status_category` | Status category |
| `created_date` | Issue creation timestamp |
| `created_year_month` | Creation year-month for analysis |
| `total_hours_logged` | Total hours logged on this issue |
| `is_done` | Whether issue is completed |
| `is_overdue` | Whether issue is overdue |

## `core.fact_worklogs`
Worklog fact table (incremental) with denormalized context. Stores time tracking entries with issue and user context for efficient time-based analysis. Use this table for: - Time tracking reports - Resource utilization analysis - Project effort tracking

| Column | Description |
|--------|-------------|
| `worklog_id` | Primary key - Unique worklog identifier |
| `issue_key` | Foreign key to dim_issues |
| `project_key` | Foreign key to dim_projects |
| `author_id` | Foreign key to dim_users (author) |
| `author_name` | Worklog author name |
| `work_started_date` | When the work started |
| `time_spent_seconds` | Time spent in seconds |
| `time_spent_hours` | Time spent in hours |
| `time_spent_person_days` | Time spent in person days (8h = 1 day) |
| `work_year_month` | Year-month of work for analysis |

## `core.fact_project_budget`
Project budget fact table from PBB issues. Budget information from PBB (Proje Butce Bilgileri) issues linked to projects for budget tracking and analysis. Use this table for: - Budget tracking - Budget vs actual analysis - Resource planning

| Column | Description |
|--------|-------------|
| `issue_id` | Primary key - PBB issue ID |
| `issue_key` | PBB issue key |
| `budget_description` | Budget item description |
| `budget_person_days` | Budget in person days |
| `budgeting_year` | Budgeting year |
| `project_choice` | Selected project |
| `linked_project_key` | Foreign key to dim_projects |
| `budget_status` | Budget status (Completed, Active, Pending) |

## `core.fact_worklogs_snapshot`
Worklog snapshot fact table for closed periods. Stores aggregated worklog data for closed periods (year-month). Only includes data from periods marked as closed in dim_date. Provides historical snapshots that won't change. Use this table for: - Historical reporting - Period-over-period comparisons - Budget vs actual for closed periods

| Column | Description |
|--------|-------------|
| `snapshot_key` | Primary key - Composite of period, project, user, issue type |
| `snapshot_period` | Year-month of the snapshot (YYYY-MM) |
| `period_start_date` | First day of the period |
| `period_end_date` | Last day of the period |
| `project_key` | Foreign key to dim_projects |
| `author_id` | Foreign key to dim_users |
| `issue_type` | Issue type |
| `worklog_count` | Number of worklogs in period |
| `total_hours_logged` | Total hours logged in period |
| `total_person_days` | Total person days in period |
| `is_period_closed` | Always true (only closed periods) |

## `core.fact_operation_efforts`
Operation Efforts Fact Model. Provides period-based planned and actual effort hours for projects with variance analysis. Used for operational tracking, resource planning, and performance monitoring.

| Column | Description |
|--------|-------------|
| `period` | Period in YYYY-MM format (e.g., 2025-01) |
| `project_id` | Jira project ID (string) |
| `project_name` | Project name for reference |
| `month_num` | Month number (1-12) |
| `month_name` | Month name (January, February, etc.) |
| `planned_effort` | Planned effort hours for the month |
| `actual_effort` | Actual effort hours logged for the month |
| `variance_hours` | Effort variance in hours (actual - planned). Positive means overrun, negative means under budget. |
| `variance_percent` | Effort variance as percentage ((actual - planned) / planned * 100) |
| `performance_indicator` | Performance category based on variance: - On Track: actual <= planned - Slight Overrun: 0-10% over planned - Moderate Overrun: 10-20% over planned - Significant Overrun: >20% over planned - Incomplete Data: missing planned or actual |
| `etl_date` | Original ETL load timestamp from staging |
| `dlt_load_id` | DLT load ID for tracking |
| `_etl_date` | Mart layer ETL timestamp |

## `core.map_issue_links`
Issue links bridge table for many-to-many relationships. Stores issue relationships (Blocks, Duplicates, Relates To, etc.) with enriched context from both source and target issues. Use this table for: - Dependency analysis - Blocker identification - Cross-project relationship analysis

| Column | Description |
|--------|-------------|
| `link_id` | Primary key - DLT record ID |
| `source_issue_key` | Foreign key to dim_issues (source) |
| `target_issue_key` | Foreign key to dim_issues (target) |
| `relationship_type` | Type of relationship |
| `link_direction` | Link direction (inward/outward) |
| `is_cross_project_link` | Whether link crosses projects |
| `is_active_blocker` | Whether this is an active blocking relationship |

## `core.map_issue_subtasks`
Issue subtasks bridge table for parent-child relationships. Connects parent issues with their subtasks with enriched context from both sides. Use this table for: - Subtask progress tracking - Parent issue completion analysis - Work breakdown analysis

| Column | Description |
|--------|-------------|
| `subtask_link_id` | Primary key - DLT record ID |
| `parent_key` | Foreign key to dim_issues (parent) |
| `subtask_key` | Foreign key to dim_issues (subtask) |
| `subtask_status` | Current subtask status |
| `is_subtask_done` | Whether subtask is completed |
| `subtask_resolution_days` | Days to resolve subtask |

## `mart.fact_distributed_efforts_adjustment`
Financial Adjustment Fact Model. Provides period-based manual adjustments for projects that override calculated distributed efforts. Used in financial dashboard to apply manual corrections to effort distributions.

| Column | Description |
|--------|-------------|
| `period` | Period in YYYY-MM format (e.g., 2025-01) |
| `project_id` | Jira project ID (string) |
| `project_name` | Project name for reference |
| `month_num` | Month number (1-12) |
| `month_name` | Month name (January, February, etc.) |
| `adjustment_amount` | Manual adjustment value to override calculated efforts |
| `etl_date` | ETL load timestamp |
| `dlt_load_id` | DLT load ID for tracking |

## `staging.stg_jira__projects`
Staging view for Jira projects with standardized column names and portfolio properties

| Column | Description |
|--------|-------------|
| `project_id` | Primary key - Unique project identifier from Jira |
| `project_key` | Project key (e.g., SD, DEV, PM) |
| `project_name` | Human-readable project name |
| `project_description` | Project category description |
| `project_type` | Type of project (software, business, service_desk) |
| `is_private` | Whether the project is private |
| `business_line` | Portfolio property - Business Line |
| `customer` | Portfolio property - Customer |
| `hosting` | Portfolio property - Hosting type |
| `portfolio_id` | Portfolio property - Portfolio ID |
| `it_domain` | Portfolio property - IT Domain |
| `product` | Portfolio property - Product |
| `product_group` | Portfolio property - Product Group |
| `tribe` | Portfolio property - Tribe |
| `open_closed` | Portfolio property - Open/Closed status |

## `staging.stg_jira__issues`
Staging view for Jira issues with type casting and renaming

| Column | Description |
|--------|-------------|
| `issue_id` | Primary key - Unique issue identifier from Jira |
| `issue_key` | Issue key (e.g., SD-1234) |
| `issue_summary` | Issue title/summary |
| `issue_type` | Type of issue (Bug, Story, Task, Epic, etc.) |
| `priority` | Issue priority (Highest, High, Medium, Low, Lowest) |
| `status_name` | Current status name |
| `status_category` | Status category (To Do, In Progress, Done) |
| `project_id` | Project ID this issue belongs to |
| `project_key` | Project key this issue belongs to |
| `project_name` | Project name this issue belongs to |
| `assignee_id` | User ID of assignee |
| `assignee_name` | Display name of assignee |
| `reporter_id` | User ID of reporter |
| `reporter_name` | Display name of reporter |
| `creator_id` | User ID of creator |
| `creator_name` | Display name of creator |
| `parent_id` | Parent issue ID (for subtasks) |
| `parent_key` | Parent issue key (for subtasks) |
| `is_subtask` | Boolean flag indicating if this is a subtask |
| `created_date` | Issue creation timestamp |
| `updated_date` | Last update timestamp |
| `resolution` | Resolution status |
| `resolution_date` | Resolution timestamp |
| `due_date` | Due date |
| `description` | Parsed plain text description extracted from Atlassian Document Format JSON |
| `labels` | Parsed comma-separated labels string |

## `staging.stg_jira__issue_links`
Staging view for issue relationships (blocks, duplicates, relates to, etc.)

| Column | Description |
|--------|-------------|
| `source_issue_key` | Source issue in the relationship |
| `target_issue_key` | Target issue in the relationship |
| `relationship_type` | Type of relationship (Blocks, Duplicate, Relates, etc.) |
| `link_direction` | Direction of link (inward/outward) |
| `_dlt_id` | DLT record identifier (unique key) |

## `staging.stg_jira__issue_subtasks`
Staging view for parent-child subtask relationships

| Column | Description |
|--------|-------------|
| `parent_key` | Parent issue key |
| `subtask_key` | Subtask issue key |
| `subtask_summary` | Subtask title |
| `subtask_status` | Current status of subtask |
| `_dlt_id` | DLT record identifier (unique key) |

## `staging.stg_jira__issue_custom_fields`
Staging view for custom field values parsed from JSON storage - one row per field per issue

| Column | Description |
|--------|-------------|
| `custom_field_id` | Primary key - Composite ID (issue_key + field_id) |
| `issue_key` | Issue this custom field belongs to |
| `field_id` | Custom field ID (e.g., customfield_10037) |
| `field_name` | Human-readable field name (e.g., Story Points, Epic Link) |
| `field_type` | Field type (numeric, text, document, user, array, other) |
| `raw_value` | Original raw value from JSON |
| `field_value_parsed` | Parsed field value with JSON extraction applied |
| `is_json_value` | Flag indicating if value is a JSON object or array |
| `is_null_value` | Flag indicating if value is null or empty |

## `staging.stg_jira__users`
Staging view for Jira users enriched with HR data

| Column | Description |
|--------|-------------|
| `user_id` | Primary key - Unique user account ID |
| `display_name` | User's display name |
| `email` | User's email address |
| `full_name` | Full name from HR data or display_name |
| `is_active` | Combined active status from Jira and HR |
| `is_jira_active` | Jira account active status |
| `hr_status` | HR system status |
| `account_type` | Type of account (atlassian, app, customer) |
| `unit` | Organizational unit from HR |
| `team` | Team name from HR |
| `manager_director` | Manager/Director from HR |
| `manager_deputy_gm` | Deputy GM Manager from HR |
| `deputy_gm_upper_unit` | Deputy GM upper unit from HR |
| `manages_team` | Team management status from HR |
| `outsource_inhouse` | Outsource or In-house flag from HR |
| `company_info` | Company information from HR |
| `employment_start_date` | Employment start date from HR |
| `has_hr_data` | Flag indicating if HR data exists for this user |

## `staging.stg_jira__worklogs`
Staging view for time tracking worklogs

| Column | Description |
|--------|-------------|
| `worklog_id` | Primary key - Unique worklog identifier |
| `issue_key` | Issue this worklog is logged against |
| `issue_id` | Issue ID this worklog is logged against |
| `author_id` | User ID of worklog author |
| `author_name` | Display name of worklog author |
| `work_started_date` | When the work started |
| `time_spent_display` | Human-readable time spent (e.g., '2h 30m') |
| `time_spent_seconds` | Time spent in seconds |
| `created_date` | Worklog creation timestamp |
| `updated_date` | Last update timestamp |

## `staging.stg_jira__hr_users`
Staging view for HR user data from Jira HR project

| Column | Description |
|--------|-------------|
| `user_account_id` | Jira account ID of the user |
| `user_name` | User name from custom field |
| `user_display_name` | Full name (name_surname) |
| `team_name` | Team name |
| `unit_name` | Organizational unit |
| `manager_name` | Manager/Director name |
| `deputy_gm_name` | Deputy GM Manager |
| `deputy_gm_upper_unit` | Deputy GM upper unit |
| `is_active` | Employment status (Active/Inactive) |
| `is_manages_team` | Team management status |
| `is_outsource_inhouse` | Outsource or In-house flag |
| `start_date` | Employment start date |
| `company_info` | Company information |
| `issue_id` | HR issue ID |
| `issue_key` | Primary key - HR issue key |
| `created_date` | Record creation timestamp |

## `staging.stg_jira__pbb_issues`
Staging view for PBB (Project Budget) issues from Jira

| Column | Description |
|--------|-------------|
| `issue_id` | Primary key - Unique PBB issue ID |
| `issue_key` | PBB issue key |
| `issue_summary` | Issue title/summary |
| `budget_person_days` | Budget in person days |
| `project_choice` | Project choice selection |
| `budgeting_year` | Budgeting year |
| `status_name` | Current status |
| `status_category` | Status category |
| `assignee_id` | Assignee account ID |
| `assignee_name` | Assigned person |
| `reporter_id` | Reporter account ID |
| `reporter_name` | Reporter name |
| `creator_id` | Creator account ID |
| `creator_name` | Creator name |
| `issue_type` | Issue type |
| `priority` | Priority level |
| `resolution` | Resolution status |
| `resolution_date` | Resolution timestamp |
| `created_date` | Creation timestamp |
| `updated_date` | Last update timestamp |
| `description` | Parsed plain text description extracted from Atlassian Document Format JSON |

## `staging.stg_jira__project_properties`
Staging view for Jira project properties with parsed values

| Column | Description |
|--------|-------------|
| `property_id` | Primary key - Composite ID (project_id + property_key) |
| `project_id` | Project ID |
| `project_key` | Project key |
| `property_key` | Original property key |
| `property_name_clean` | Standardized property name |
| `property_category` | Property category (portfolio, jira_integration, etc.) |
| `raw_value` | Original value |
| `cleaned_value` | Cleaned value with JSON conversion |
| `parsed_value` | Final parsed value |
| `is_json_value` | Flag for JSON values |
| `is_null_value` | Flag for null values |
| `is_boolean_value` | Flag for boolean values |

## `staging.stg_shrp__projects`
Staging model for SharePoint Projects list. Master project registry mapping Jira project IDs to SharePoint project metadata.

| Column | Description |
|--------|-------------|
| `item_id` | SharePoint item ID (unique within list) |
| `project_title` | Project title/name |
| `jira_project_id` | Jira project ID mapping |
| `project_id_numeric` | Numeric project identifier |
| `project_type` | Project type category (e.g., Maintenance & CRs) |
| `modified_at` | Last modification timestamp |
| `created_at` | Creation timestamp |

## `staging.stg_shrp__proje_inv`
Staging model for SharePoint Project Inventory list. Detailed project tracking with status, timeline, scope, and risk information. This is the main project status tracking table used for executive reporting.

| Column | Description |
|--------|-------------|
| `item_id` | SharePoint item ID (unique within list) |
| `project_code` | Project code (e.g., M0072) |
| `project_name` | Project internal name |
| `customer_name` | Customer/brand name |
| `product_family` | Product family (e.g., PF & POS, Core Banking) |
| `product_category` | Product category |
| `product_subcategory` | Product subcategory |
| `hosting_type` | Hosting type (HostingCustomer, HostingFirmaX) |
| `business_model` | Business model (B2B, B2B2C) |
| `project_code_ref` | Project code reference |
| `project_phase` | Project phase/status (Pilot, In Progress, Closed) |
| `jira_project_id` | Related Jira project ID |
| `tracking_status` | Project tracking status (On Track, Delayed) |
| `progress_notes` | Current progress description and notes |
| `timeline_notes` | Timeline milestones and dates |
| `scope_notes` | Scope definition |
| `project_category` | Category classification (Customer, Internal) |
| `is_executive_dashboard` | Flag for executive dashboard visibility |
| `is_strategic_portfolio` | Strategic portfolio flag |
| `risk_notes` | Current risks and problems description |
| `scope_risk_status` | Scope risk status (On Track, Risky) |
| `escalation_count` | Escalation count/level |
| `customer_responsibility` | Customer responsibility indicator |
| `has_risk_flag` | Risk exists flag |
| `project_manager_lookup_id` | Project manager lookup reference |
| `portfolio_manager_lookup_id` | Portfolio manager lookup reference |
| `it_tribe_lead_lookup_id` | IT tribe lead lookup reference |
| `updated_at` | Update timestamp |
| `modified_at` | Last modification timestamp |
| `created_at` | Creation timestamp |

## `staging.stg_shrp__proje_risks`
Staging model for SharePoint Project Risks list. Risk tracking entries linked to projects in the Project Inventory list.

| Column | Description |
|--------|-------------|
| `item_id` | SharePoint item ID (unique within list) |
| `project_code` | Project code reference |
| `risk_description` | Risk description |
| `risk_status` | Risk status (Risk Giderildi, Active, etc.) |
| `proje_inv_lookup_id` | Link to project in proje_inv list |
| `project_names_lookup_id` | Project names lookup reference |
| `modified_at` | Last modification timestamp |
| `created_at` | Creation timestamp |

## `staging.stg_shrp__issue_type`
Staging model for SharePoint Issue Type list. Master data for Jira issue type classifications. Maps issue types to expense categories (Expensed vs Capitalized) for financial reporting.

| Column | Description |
|--------|-------------|
| `item_id` | SharePoint item ID (unique within list) |
| `issue_type_name` | Issue type name (e.g., Analysis, Development, Testing) |
| `expense_classification` | Expense classification (Expensed, Capitalized) |
| `jira_issue_type_id` | Jira issue type ID |
| `issue_type_category` | Category (SDLC Tasks, Infrastructure & Technical Works, etc.) |
| `is_active` | Active status flag |
| `modified_at` | Last modification timestamp |
| `created_at` | Creation timestamp |

## `staging.stg_shrp__issue_type_inventory`
Staging model for SharePoint Issue Type Inventory list. Task type definitions with detailed descriptions. Used for categorizing and describing different types of work.

| Column | Description |
|--------|-------------|
| `item_id` | SharePoint item ID (unique within list) |
| `task_type_title` | Task type title |
| `task_type_category` | Task type category (General Tasks, SDLC Tasks, etc.) |
| `task_type_description` | Task type description |
| `expense_classification` | Expense classification (Expensed, Capitalized) |
| `task_description` | Full description of the task type |
| `modified_at` | Last modification timestamp |
| `created_at` | Creation timestamp |

## `staging.stg_shrp__pbi_info`
Staging model for SharePoint PBI Info list. Power BI project/team mapping information. Maps Jira project IDs to team names for Power BI reporting.

| Column | Description |
|--------|-------------|
| `item_id` | SharePoint item ID (unique within list) |
| `jira_project_id` | Jira project ID |
| `team_name` | Team/project name mapping for Power BI |
| `modified_at` | Last modification timestamp |
| `created_at` | Creation timestamp |

## `staging.stg_shrp__capex_opex_adjustment`
Staging model for SharePoint CAPEX/OPEX Adjustment Excel file. Unpivots monthly CAPEX and OPEX ratio columns into a long format with one row per project per month. Each row contains both CAPEX and OPEX ratios for a given project and month.

| Column | Description |
|--------|-------------|
| `year` | Year for the adjustments |
| `project_id` | Project ID (Jira project ID) |
| `project` | Project name |
| `period` | Period in YYYY-MM format |
| `month_num` | Month number (1-12) |
| `month_name` | Month name (January, February, etc.) |
| `ratio_capex` | CAPEX ratio for the month |
| `ratio_opex` | OPEX ratio for the month |
| `_etl_date` | ETL load timestamp |
| `_dlt_load_id` | DLT load identifier |
| `_dlt_id` | DLT record identifier |

## `staging.stg_shrp__operation_efforts`
Staging model for SharePoint Operation Efforts Excel file. Unpivots monthly planned and actual effort hours into long format with one row per project per month. Each row contains both planned and actual effort values for comparison and variance analysis.

| Column | Description |
|--------|-------------|
| `year` | Year for the operation efforts |
| `project_id` | Project ID (Jira project ID) |
| `project_name` | Project name |
| `period` | Period in YYYY-MM format (e.g., 2025-01) |
| `month_num` | Month number (1-12) |
| `month_name` | Month name (January, February, etc.) |
| `planned_effort` | Planned effort hours for the month |
| `actual_effort` | Actual effort hours logged for the month |
| `_etl_date` | ETL load timestamp |
| `_dlt_load_id` | DLT load ID for tracking |
| `_dlt_id` | DLT unique record ID |

