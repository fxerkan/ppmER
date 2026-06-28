# Metabase Dashboard Setup

After starting the stack and running the first data load, follow these steps to create your PPM dashboards.

## First-Time Setup

1. Open Metabase: http://localhost:3000
2. Complete the setup wizard
3. Add your database: **PostgreSQL** at `postgres:5432`, database `ppm_datawarehouse`, user `ppm_user`
4. Create the 5 dashboards below as "Saved Questions" then add them to a dashboard

---

## Dashboard 1: Portfolio Overview

**Purpose**: High-level view of all projects.

```sql
-- Project summary with issue counts and logged hours
SELECT
    p.project_key,
    p.project_name,
    COUNT(DISTINCT i.issue_key) AS total_issues,
    COUNT(DISTINCT CASE WHEN i.status_category != 'Done' THEN i.issue_key END) AS open_issues,
    COUNT(DISTINCT CASE WHEN i.status_category = 'Done' THEN i.issue_key END) AS closed_issues,
    ROUND(SUM(w.time_spent_hours)::numeric, 1) AS total_logged_hours
FROM core.dim_projects p
LEFT JOIN core.fact_issues i ON p.project_key = i.project_key
LEFT JOIN core.fact_worklogs w ON i.issue_key = w.issue_key
GROUP BY p.project_key, p.project_name
ORDER BY total_logged_hours DESC NULLS LAST;
```

---

## Dashboard 2: Team Workload

**Purpose**: Hours per user per week to spot overload and gaps.

```sql
-- Weekly hours per user (last 12 weeks)
SELECT
    u.display_name,
    DATE_TRUNC('week', w.started_at) AS week_start,
    ROUND(SUM(w.time_spent_hours)::numeric, 1) AS hours_logged
FROM core.fact_worklogs w
JOIN core.dim_users u ON w.author_account_id = u.account_id
WHERE w.started_at >= NOW() - INTERVAL '12 weeks'
GROUP BY u.display_name, DATE_TRUNC('week', w.started_at)
ORDER BY week_start DESC, hours_logged DESC;
```

```sql
-- Top 10 users by total logged hours this month
SELECT
    u.display_name,
    u.email_address,
    ROUND(SUM(w.time_spent_hours)::numeric, 1) AS hours_this_month
FROM core.fact_worklogs w
JOIN core.dim_users u ON w.author_account_id = u.account_id
WHERE DATE_TRUNC('month', w.started_at) = DATE_TRUNC('month', NOW())
GROUP BY u.display_name, u.email_address
ORDER BY hours_this_month DESC
LIMIT 10;
```

---

## Dashboard 3: Sprint Progress

**Purpose**: Issue status breakdown per project.

```sql
-- Issues by status category per project
SELECT
    i.project_key,
    i.status_category,
    i.status_name,
    COUNT(*) AS issue_count
FROM core.fact_issues i
WHERE i.issue_type != 'Sub-task'
GROUP BY i.project_key, i.status_category, i.status_name
ORDER BY i.project_key, i.status_category;
```

```sql
-- Epic progress: completion percentage
SELECT
    i.project_key,
    i.epic_name,
    COUNT(*) AS total_issues,
    COUNT(CASE WHEN i.status_category = 'Done' THEN 1 END) AS done_issues,
    ROUND(
        100.0 * COUNT(CASE WHEN i.status_category = 'Done' THEN 1 END) / COUNT(*),
        1
    ) AS completion_pct
FROM core.fact_issues i
WHERE i.epic_name IS NOT NULL
  AND i.issue_type != 'Sub-task'
GROUP BY i.project_key, i.epic_name
ORDER BY completion_pct ASC;
```

---

## Dashboard 4: Missing Effort Report

**Purpose**: Find issues that should have logged hours but don't.

```sql
-- Issues with no worklogs (open, assigned, older than 7 days)
SELECT
    i.project_key,
    i.issue_key,
    i.summary,
    i.issue_type,
    i.assignee_display_name,
    i.status_name,
    i.created_at::date AS created_date,
    NOW()::date - i.created_at::date AS age_days
FROM core.fact_issues i
LEFT JOIN core.fact_worklogs w ON i.issue_key = w.issue_key
WHERE w.issue_key IS NULL
  AND i.status_category NOT IN ('Done')
  AND i.issue_type NOT IN ('Epic', 'Sub-task')
  AND i.created_at < NOW() - INTERVAL '7 days'
ORDER BY age_days DESC;
```

```sql
-- Or use the pre-built mart model if available
SELECT * FROM mart.rpt_missing_effort
ORDER BY age_days DESC
LIMIT 100;
```

---

## Dashboard 5: Historical Trend

**Purpose**: Issue creation and resolution velocity over time.

```sql
-- Monthly issue creation vs resolution trend
SELECT
    DATE_TRUNC('month', created_at) AS month,
    COUNT(*) AS issues_created,
    COUNT(CASE WHEN status_category = 'Done' THEN 1 END) AS issues_resolved,
    COUNT(*) - COUNT(CASE WHEN status_category = 'Done' THEN 1 END) AS backlog_delta
FROM core.fact_issues
WHERE issue_type NOT IN ('Sub-task', 'Epic')
  AND created_at >= NOW() - INTERVAL '12 months'
GROUP BY DATE_TRUNC('month', created_at)
ORDER BY month;
```

```sql
-- Cumulative worklog hours over time
SELECT
    DATE_TRUNC('month', started_at) AS month,
    ROUND(SUM(time_spent_hours)::numeric, 1) AS hours_logged,
    COUNT(DISTINCT issue_key) AS issues_worked
FROM core.fact_worklogs
WHERE started_at >= NOW() - INTERVAL '12 months'
GROUP BY DATE_TRUNC('month', started_at)
ORDER BY month;
```

---

## Tips

- Use **Metabase Questions** (not SQL directly) for interactive filtering
- Add date filters to all dashboards so users can drill into time ranges
- Pin the Portfolio Overview dashboard as the home page
- Set up email subscriptions for the Missing Effort report (weekly digest)
