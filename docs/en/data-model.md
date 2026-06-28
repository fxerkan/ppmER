# Data Model Documentation

## Why a Snapshot-Based Historical Data Model?

Most Jira analytics integrations pull the *current* state of your data. This means:

- You can't see what the status of an issue was last month
- You can't measure how long issues spent in each status
- If someone deletes a worklog in Jira, your history is gone
- Capacity reports become inaccurate because effort isn't tied to calendar periods

This stack uses a **snapshot-based historical model** that solves all of these:

- Every time the pipeline runs, it captures the current state as a timestamped snapshot
- Worklogs are stored permanently even if deleted in Jira
- Effort is distributed across calendar days/weeks/months for accurate capacity planning
- Status change velocity can be calculated from snapshot deltas

---

## 3-Layer Architecture

```
Layer 1: STAGING
  - Source: raw_jira schema (loaded by dlt)
  - Purpose: type casting, column renaming, basic deduplication
  - Naming: stg_jira__<entity>

Layer 2: CORE
  - Source: staging views
  - Purpose: business logic, dimension/fact modeling, snapshot management
  - Naming: dim_<entity>, fact_<entity>

Layer 3: MARTS
  - Source: core tables
  - Purpose: business-ready aggregations, KPIs, exception reports
  - Naming: mart_<name>, agg_<name>, rpt_<name>
```

---

## Entity Relationship Overview

```
dim_projects ----+
                 |
dim_users -------+----> fact_worklogs
                 |
dim_issues ------+----> fact_issues
                 |
                 +----> fact_distributed_efforts
```

---

## Table Descriptions

### Staging Layer

| Model | Source Table | Description |
|-------|-------------|-------------|
| `stg_jira__issues` | `raw_jira.issues` | All Jira issues with typed columns |
| `stg_jira__worklogs` | `raw_jira.worklogs` | All worklog entries |
| `stg_jira__users` | `raw_jira.users` | Jira user accounts |
| `stg_jira__projects` | `raw_jira.projects` | Jira projects |
| `stg_jira__issue_links` | `raw_jira.issue_links` | Issue relationships (blocks, relates to, etc.) |
| `stg_jira__issue_subtasks` | `raw_jira.issue_subtasks` | Parent-child issue relationships |
| `stg_jira__issue_custom_fields` | `raw_jira.issue_custom_fields` | Custom field values per issue |
| `stg_jira__project_properties` | `raw_jira.project_properties` | Project-level configuration data |

### Core Layer

| Model | Type | Description |
|-------|------|-------------|
| `dim_projects` | Dimension | Project attributes (key, name, type, lead) |
| `dim_projects_snapshot` | Snapshot | Historical project state over time |
| `dim_issues` | Dimension | Current issue state |
| `dim_issues_snapshot` | Snapshot | Issue state at each pipeline run — use this for trend analysis |
| `dim_users` | Dimension | User profiles and team assignments |
| `fact_worklogs` | Fact | Every worklog entry with author, issue, duration, timestamp |
| `fact_issues` | Fact | Aggregated issue metrics (story points, time estimates vs actuals) |
| `fact_distributed_efforts` | Fact | Worklog effort distributed across calendar days for capacity reporting |

### Key Design Decisions

#### `dim_issues_snapshot`
Each time the pipeline runs, a new row is written with `snapshot_date = TODAY`. This lets you:
```sql
-- Status of all issues at end of last quarter
SELECT issue_key, status_name, assignee_display_name
FROM core.dim_issues_snapshot
WHERE snapshot_date = '2024-12-31'
```

#### `fact_distributed_efforts`
A worklog of "8 hours logged on Monday" is stored as a single row. But for monthly capacity reports, that 8h should appear in January's total. `fact_distributed_efforts` handles this by distributing effort across the relevant calendar period (day/week/month/quarter):
```sql
SELECT
    calendar_month,
    project_key,
    SUM(distributed_hours) as monthly_effort
FROM core.fact_distributed_efforts
GROUP BY calendar_month, project_key
```

#### `fact_worklogs`
Immutable historical record. Even if a worklog is deleted from Jira, it remains here. The `is_deleted` flag is set to `true` when the source record disappears.

### Marts Layer

| Model | Description |
|-------|-------------|
| `mart_portfolio_dashboard` | One row per project with all KPIs (issues, hours, health score) |
| `agg_project_health` | Project health indicators: overdue count, missing effort, velocity trend |
| `rpt_missing_effort` | Issues that should have worklogs but don't (configurable thresholds) |
| `fact_financial_dashboard_2025` | Financial capacity view: planned vs actual effort by period |
| `fact_financial_dashboard_2026` | Same model for current year |

---

## SQL Examples

### How many hours logged per project this month?
```sql
SELECT
    p.project_name,
    SUM(w.time_spent_hours) as hours
FROM core.fact_worklogs w
JOIN core.dim_projects p ON w.project_key = p.project_key
WHERE DATE_TRUNC('month', w.started_at) = DATE_TRUNC('month', NOW())
GROUP BY p.project_name
ORDER BY hours DESC;
```

### Which issues changed status in the last 7 days?
```sql
SELECT
    s1.issue_key,
    s1.status_name as old_status,
    s2.status_name as new_status,
    s2.snapshot_date as changed_on
FROM core.dim_issues_snapshot s1
JOIN core.dim_issues_snapshot s2
    ON s1.issue_key = s2.issue_key
    AND s2.snapshot_date = s1.snapshot_date + INTERVAL '1 day'
    AND s1.status_name != s2.status_name
WHERE s2.snapshot_date >= NOW() - INTERVAL '7 days';
```
